# meta_ads/agent.py — оркестратор: создание кампаний, ежедневная оптимизация, отчёт.
#
#   setup     — создаёт недостающие кампании (кампания → группа → 3 объявления), всё на ПАУЗЕ
#   activate  — включает кампании после того, как ты проверила их в Ads Manager
#   optimize  — раз в день: перераспределяет бюджет, ставит на паузу слабые объявления,
#               заменяет выгоревшие новыми текстами от Claude, шлёт отчёт в Telegram
#   report    — то же чтение статистики, но без изменений
import json
import os
from datetime import date, datetime, timedelta, timezone

from paths import dpath
from telegram_notify import notify
from . import budget, copywriter
from .api import MetaAPI, MetaAPIError, count_action
from .targeting import build_targeting

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "campaigns.json")
STATE_PATH = dpath("meta_ads_state.json")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    env_total = os.getenv("META_ADS_TOTAL_DAILY_BUDGET")
    if env_total:
        cfg["total_daily_budget"] = float(env_total)
    return cfg


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"campaigns": {}, "lookup_cache": {}, "history": []}


def save_state(state, api):
    if not api.live:
        print("[META] dry-run — состояние не сохраняю")
        return
    state["history"] = state.get("history", [])[-90:]
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def _promoted_object(camp):
    pixel = camp.get("pixel_id") or os.getenv("META_PIXEL_ID", "")
    if camp.get("optimization_goal") == "OFFSITE_CONVERSIONS":
        if not pixel:
            raise ValueError("для OFFSITE_CONVERSIONS нужен pixel_id (в кампании или META_PIXEL_ID)")
        return {"pixel_id": pixel, "custom_event_type": camp.get("custom_event_type", "LEAD")}
    return None


def _image_path(camp):
    p = camp.get("image", "")
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def _validate(key, camp, page_id):
    problems = []
    if not camp.get("link", "").startswith("https://"):
        problems.append("link — адрес посадочной страницы (https://…)")
    if not camp.get("image") or not os.path.isfile(_image_path(camp)):
        problems.append(f"image — путь к картинке 1080×1080 (сейчас: «{camp.get('image', '')}»)")
    if not page_id:
        problems.append("META_PAGE_ID — id Facebook-страницы, от имени которой идёт реклама")
    return [f"{key}: {p}" for p in problems]


def _new_ad(api, entry, camp, copy, page_id, status="PAUSED"):
    n = len(entry["ads"]) + 1
    name = f"{camp['name'][:40]} · v{n}"
    creative = api.create_creative(name, page_id, camp["link"], copy, entry["image_hash"], camp.get("cta", "LEARN_MORE"),
                                   os.getenv("META_IG_USER_ID", ""))
    ad = api.create_ad(entry["adset_id"], name, creative["id"], status)
    entry["ads"].append({"ad_id": ad["id"], "creative_id": creative["id"], "copy": copy,
                         "created": date.today().isoformat()})
    return ad["id"]


# ---------------- setup ----------------

def setup(only=None):
    cfg, state, api = load_config(), load_state(), MetaAPI()
    page_id = os.getenv("META_PAGE_ID", "").strip()
    todo = {k: c for k, c in cfg["campaigns"].items() if (not only or k in only) and k not in state["campaigns"]}
    if not todo:
        print("[META] все кампании уже созданы")
        return
    problems = [p for k, c in todo.items() for p in _validate(k, c, page_id)]
    if problems:
        print("[META] заполни перед запуском:\n  " + "\n  ".join(problems))
        return
    if api.live and not api.configured:
        raise SystemExit("META_ACCESS_TOKEN и META_AD_ACCOUNT_ID обязательны в режиме META_ADS_LIVE=true")

    start_budget = min(max(cfg["total_daily_budget"] / len(cfg["campaigns"]), cfg["min_daily_budget"]),
                       cfg["max_daily_budget"])
    for key, camp in todo.items():
        print(f"\n[META] === {camp['name']} ===")
        targeting = build_targeting(api, cfg, camp, state.setdefault("lookup_cache", {})) if api.token else \
            {"geo_locations": {"countries": camp.get("countries") or cfg["countries"]}}
        print(f"[META] таргетинг: {json.dumps(targeting, ensure_ascii=False)}")
        c = api.create_campaign(camp["name"], camp["objective"], start_budget)
        s = api.create_adset(c["id"], f"{camp['name'][:50]} · СНГ", targeting, camp["optimization_goal"],
                             _promoted_object(camp))
        entry = {"campaign_id": c["id"], "adset_id": s["id"], "image_hash": api.upload_image(_image_path(camp)),
                 "created": date.today().isoformat(), "ads": []}
        for copy in copywriter.generate(camp, n=3):
            _new_ad(api, entry, camp, copy, page_id)
        state["campaigns"][key] = entry
        save_state(state, api)  # после каждой кампании — чтобы сбой на следующей не потерял id
    msg = "Кампании созданы на паузе. Проверь их в Ads Manager и запусти: python meta_ads_agent.py activate"
    print(f"\n[META] {msg}")
    if api.live:
        notify(f"📣 Meta Ads: {', '.join(todo)} — {msg}")


# ---------------- activate ----------------

def activate(only=None):
    state, api = load_state(), MetaAPI()
    for key, entry in state["campaigns"].items():
        if only and key not in only:
            continue
        for ad in entry["ads"]:
            if not ad.get("paused_by_agent"):
                api.set_status(ad["ad_id"], "ACTIVE")
        api.set_status(entry["adset_id"], "ACTIVE")
        api.set_status(entry["campaign_id"], "ACTIVE")
        print(f"[META] {key}: включена")


# ---------------- optimize / report ----------------

def _age_days(created_time):
    try:
        t = datetime.strptime(created_time, "%Y-%m-%dT%H:%M:%S%z")
        return (datetime.now(timezone.utc) - t).days
    except (TypeError, ValueError):
        return 99


def _daily_series(rows, days, action):
    """[(spend, results)] за каждый из последних `days` дней, вчерашний первым.
    Дни без показов Meta не возвращает — для них ставим нули."""
    by_day = {r["date_start"]: (float(r.get("spend", 0) or 0), count_action(r, action)) for r in rows}
    yesterday = date.today() - timedelta(days=1)
    return [by_day.get((yesterday - timedelta(days=i)).isoformat(), (0.0, 0.0)) for i in range(days)]


def optimize(apply=True):
    cfg, state, api = load_config(), load_state(), MetaAPI()
    if not api.configured:
        print("[META] нет META_ACCESS_TOKEN / META_AD_ACCOUNT_ID — оптимизировать нечего")
        return
    if not state["campaigns"]:
        print("[META] кампаний в состоянии нет — сначала python meta_ads_agent.py setup")
        return
    days, rules, page_id = cfg["lookback_days"], cfg["ad_rules"], os.getenv("META_PAGE_ID", "").strip()
    currency = api.account_info().get("currency", "")

    stats, report = [], []
    for key, entry in state["campaigns"].items():
        camp = cfg["campaigns"].get(key)
        if not camp:
            continue
        try:
            info = api.campaign(entry["campaign_id"])
        except MetaAPIError as e:
            report.append(f"⚠️ {key}: не читается ({e.user_msg})")
            continue
        if info.get("effective_status") != "ACTIVE":
            report.append(f"⏸ {camp['name']}: {info.get('effective_status')}")
            continue
        series = _daily_series(api.daily_insights(entry["campaign_id"], days), days, camp["result_action"])
        age = _age_days(info.get("created_time"))
        learning_now = any((a.get("learning_stage_info") or {}).get("status") == "LEARNING"
                           for a in api.adsets(entry["campaign_id"]))
        stats.append(budget.CampaignStats(
            key=key,
            current_budget=api.from_minor(info.get("daily_budget", 0)),
            target_cpa=float(camp["target_cpa"]),
            daily=series,
            # Даём Meta отучиться: первые learning_days дней всегда, дальше — пока группа
            # в статусе LEARNING, но не дольше недели (на малом бюджете обучение бывает вечным).
            learning=age < cfg["learning_days"] or (learning_now and age < 7),
        ))

    plan = budget.allocate(stats, cfg["total_daily_budget"], cfg["min_daily_budget"], cfg["max_daily_budget"],
                           cfg["max_daily_change"], cfg["recency_decay"])
    day_log = {"date": date.today().isoformat(), "campaigns": {}}
    for s in stats:
        camp, entry = cfg["campaigns"][s.key], state["campaigns"][s.key]
        new, why = plan[s.key]
        spend7 = sum(x for x, _ in s.daily)
        res7 = sum(r for _, r in s.daily)
        cpa = f"{spend7 / res7:.2f}" if res7 else "—"
        line = (f"• {camp['name']}\n  {days} дн: расход {spend7:.2f} {currency}, результатов {int(res7)}, "
                f"CPA {cpa} (цель {s.target_cpa})\n  бюджет {s.current_budget:.2f} → {new:.2f}: {why}")
        if apply and abs(new - s.current_budget) >= max(0.01 * s.current_budget, 0.01):
            api.set_daily_budget(entry["campaign_id"], new)

        line += _manage_ads(api, entry, camp, rules, page_id, apply)
        report.append(line)
        day_log["campaigns"][s.key] = {"spend": round(spend7, 2), "results": res7,
                                      "budget_from": s.current_budget, "budget_to": new}

    total = sum(plan[s.key][0] for s in stats)
    mode = "" if api.live else " (dry-run — изменения не применены)"
    text = (f"📣 Meta Ads — {'оптимизация' if apply else 'отчёт'}{mode}\n"
            f"Бюджет в день: {total:.2f} из {cfg['total_daily_budget']} {currency}\n\n" + "\n\n".join(report))
    print(text)
    notify(text[:4000])
    if apply:
        state.setdefault("history", []).append(day_log)
        save_state(state, api)


def _manage_ads(api, entry, camp, rules, page_id, apply):
    """Паузит слабые объявления и заменяет выгоревшие. Возвращает строки для отчёта."""
    rows = {r["ad_id"]: r for r in api.ad_insights(entry["adset_id"], 7)}
    live = {a["id"] for a in api.ads(entry["adset_id"]) if a.get("effective_status") == "ACTIVE"}
    target = float(camp["target_cpa"])
    notes, perf, refresh = [], [], False

    for ad in entry["ads"]:
        row = rows.get(ad["ad_id"])
        if not row:
            continue
        results = count_action(row, camp["result_action"])
        imps = float(row.get("impressions", 0) or 0)
        perf.append({"primary_text": ad["copy"]["primary_text"],
                     "ctr": round(float(row.get("inline_link_clicks", 0) or 0) / imps, 4) if imps else None,
                     "cpa": round(float(row["spend"]) / results, 2) if results else None})
        if ad["ad_id"] not in live:
            continue
        verdict, why = budget.ad_verdict(row, rules, target, results)
        if verdict == "pause" and len(live) > 1:
            notes.append(f"  ⛔ пауза v{entry['ads'].index(ad) + 1}: {why}")
            if apply:
                api.set_status(ad["ad_id"], "PAUSED")
                ad["paused_by_agent"] = date.today().isoformat()
            live.discard(ad["ad_id"])
        elif verdict == "refresh":
            notes.append(f"  🔁 v{entry['ads'].index(ad) + 1}: {why}")
            refresh = True

    # Новое объявление — если старые выгорели или после пауз осталось меньше двух.
    if apply and (refresh or len(live) < 2) and len(live) < rules["max_active_ads"] and page_id:
        avoid = [a["copy"]["primary_text"] for a in entry["ads"]]
        for copy in copywriter.generate(camp, n=1, performance=perf, avoid=avoid):
            ad_id = _new_ad(api, entry, camp, copy, page_id, status="ACTIVE")
            notes.append(f"  ✨ новое объявление {ad_id}: «{copy['headline']}»")
    return ("\n" + "\n".join(notes)) if notes else ""


def report():
    optimize(apply=False)
