# meta_ads/budget.py — динамическое распределение общего дневного бюджета между кампаниями.
#
# Идея: деньги перетекают туда, где результат дешевле, но плавно и без рывков.
#
#   1. Каждая кампания получает оценку стоимости результата (CPA) за последние N дней,
#      свежие дни весят больше (затухание recency_decay на каждый день назад).
#   2. CPA сглаживается априорным значением: будто у кампании уже было prior_results
#      результатов по целевой цене target_cpa. Пока данных мало, оценка остаётся около
#      цели и бюджет почти не двигается; когда результатов много — решают реальные цифры.
#   3. Эффективность = target_cpa / CPA (1.0 — ровно в цель, 2.0 — вдвое дешевле цели).
#      Вес кампании = текущий бюджет × эффективность^alpha.
#   4. Общий бюджет делится пропорционально весам, затем ограничивается:
#      - не больше ±max_daily_change от текущего бюджета за день (резкие изменения
#        перезапускают у Meta фазу обучения);
#      - в пределах [min_daily_budget, max_daily_budget];
#      - кампания в фазе обучения не трогается;
#      - кампании, которая не тратит и текущий бюджет, бюджет не растёт.
#   5. Сумма бюджетов никогда не превышает total_daily_budget.
from dataclasses import dataclass, field


@dataclass
class CampaignStats:
    key: str
    current_budget: float
    target_cpa: float
    daily: list = field(default_factory=list)   # [(spend, results)], сначала самый свежий день
    learning: bool = False                       # в фазе обучения — бюджет заморожен


def weighted_totals(daily, decay):
    spend = results = 0.0
    w = 1.0
    for s, r in daily:
        spend += s * w
        results += r * w
        w *= decay
    return spend, results


def smoothed_cpa(stats, decay, prior_results=3.0):
    spend, results = weighted_totals(stats.daily, decay)
    return (spend + prior_results * stats.target_cpa) / (results + prior_results)


def efficiency(stats, decay, prior_results=3.0):
    eff = stats.target_cpa / max(smoothed_cpa(stats, decay, prior_results), 1e-9)
    return max(0.25, min(eff, 3.0))


def spend_rate(stats, days=3):
    """Доля бюджета, которую кампания реально тратит в последние дни."""
    recent = stats.daily[:days]
    if not recent or stats.current_budget <= 0:
        return 1.0
    return sum(s for s, _ in recent) / (len(recent) * stats.current_budget)


def allocate(campaigns, total, min_b, max_b, max_change=0.2, decay=0.8, alpha=1.0, prior_results=3.0):
    """Возвращает {key: (новый_бюджет, причина)}."""
    if not campaigns:
        return {}
    eff = {c.key: efficiency(c, decay, prior_results) for c in campaigns}
    weights = {c.key: max(c.current_budget, min_b) * eff[c.key] ** alpha for c in campaigns}
    wsum = sum(weights.values())
    ideal = {k: total * w / wsum for k, w in weights.items()}

    result = {}
    for c in campaigns:
        cur = c.current_budget
        if c.learning:
            result[c.key] = [cur, "фаза обучения — не трогаю"]
            continue
        lo = max(min_b, cur * (1 - max_change))
        hi = min(max_b, cur * (1 + max_change))
        if spend_rate(c) < 0.6:
            hi = min(hi, cur)  # не тратит и то, что есть, — прибавлять бессмысленно
        new = min(max(ideal[c.key], lo), hi)
        if lo > hi:  # текущий бюджет вне [min, max] — сначала вернуть в рамки
            new = min(max(cur, min_b), max_b)
        if new > cur * 1.005:
            why = f"CPA лучше цели (эфф. {eff[c.key]:.2f}) — увеличиваю"
        elif new < cur * 0.995:
            why = f"CPA хуже цели (эфф. {eff[c.key]:.2f}) — снижаю"
        else:
            why = f"в цели (эфф. {eff[c.key]:.2f}) — без изменений"
        result[c.key] = [new, why]

    # Жёсткий потолок: если сумма выше общего бюджета — урезаем прибавки, начиная с
    # наименее эффективных кампаний, но не ниже их текущего бюджета, а затем, если всё
    # ещё много, — пропорционально всех изменяемых до минимума.
    over = sum(v[0] for v in result.values()) - total
    if over > 1e-6:
        for c in sorted(campaigns, key=lambda c: eff[c.key]):
            if over <= 1e-6:
                break
            new = result[c.key][0]
            cut = min(over, max(0.0, new - c.current_budget))
            if cut > 0:
                result[c.key][0] = new - cut
                over -= cut
        if over > 1e-6:
            free = {c.key: result[c.key][0] - min_b for c in campaigns if not c.learning and result[c.key][0] > min_b}
            fsum = sum(free.values())
            for k, room in free.items():
                result[k][0] -= min(room, over * room / fsum) if fsum else 0
                result[k][1] += "; урезано под общий бюджет"

    return {k: (round(v[0], 2), v[1]) for k, v in result.items()}


def ad_verdict(row, rules, target_cpa, result_action_count):
    """Решение по одному объявлению: 'pause', 'refresh' (выгорело) или None."""
    imps = float(row.get("impressions", 0) or 0)
    clicks = float(row.get("inline_link_clicks", 0) or 0)
    spend = float(row.get("spend", 0) or 0)
    freq = float(row.get("frequency", 0) or 0)
    if imps >= rules["min_impressions"] and clicks / imps < rules["min_ctr"]:
        return "pause", f"CTR {clicks / imps:.2%} < {rules['min_ctr']:.2%} на {int(imps)} показах"
    if spend >= 2 * rules["kill_cpa_multiplier"] * target_cpa:
        cpa = spend / result_action_count if result_action_count else float("inf")
        if cpa > rules["kill_cpa_multiplier"] * target_cpa:
            return "pause", f"CPA {cpa:.2f} > {rules['kill_cpa_multiplier']}× цели при расходе {spend:.2f}"
    if freq >= rules["fatigue_frequency"]:
        return "refresh", f"частота {freq:.1f} — аудитория устала от объявления"
    return None, ""
