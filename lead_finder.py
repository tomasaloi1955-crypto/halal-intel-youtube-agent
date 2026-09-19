# lead_finder.py — ищет свежие заказы на ИИ-автоматизацию (автопостинг, Telegram-боты,
# n8n/Make/Zapier, ИИ-агенты, чат-боты) и присылает находки в Telegram с черновиком отклика.
# Источники читаются напрямую, без поисковика: DuckDuckGo с 18.09.2026 блокирует
# GitHub Actions целиком, а ленты площадок отдают заказы без блокировок.
# FL.ru режет серверы GitHub (403) — его проверяет домашний ПК, см. LEAD_SOURCES.
# Kwork убран 19.09.2026: Kwork.ru закрывает продажи для не-граждан РФ и выводит
# деньги только на российские карты — заказы оттуда владелице бесполезны.
#   • FL.ru — RSS последних 60 заказов (≈10 часов), поэтому запуск каждые 4 часа.
#   • Freelancer.com — открытый API поиска проектов (международные заказы, en).
# Заказы из мусульманской/халяль-ниши помечаются 🕌 и идут первыми. Харам-ниши
# (казино, форекс, алкоголь, свинина, банки) отсекаются жёстко.
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET

import requests

from paths import dpath
from telegram_notify import notify, alert_fail

SEEN_FILE = dpath("seen_leads.json")
MAX_SEEN = 3000
MAX_LEADS_PER_RUN = 25
MIN_BUDGET_RUB = 1500
MIN_BUDGET_USD = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# Точные признаки заказа на автоматизацию — засчитываются и в названии, и в описании.
STRONG_KEYWORDS = [
    "автопост", "автопубликац", "автоматическая публикац", "автоматический постинг",
    "отложенный постинг", "контент-завод", "контент завод",
    "телеграм-бот", "телеграм бот", "телеграмм бот", "телеграмм-бот", "telegram-бот",
    "telegram бот", "тг бот", "тг-бот", "tg бот", "бот для телеграм", "бота для телеграм",
    "бот в телеграм", "бота в телеграм", "чат-бот", "чатбот",
    "n8n", "make.com", "zapier", "ии-агент", "ии агент", "ai-агент", "ai агент",
    "telegram bot", "chatbot", "chat bot", "ai agent",
    "autopost", "auto-post", "auto post", "scheduled posts", "social media automation",
]
# Общие слова — только в названии: в описаниях они мелькают где попало
# («сделайте без нейросетей», «автоматизация продаж» у рекламодателя).
TITLE_KEYWORDS = STRONG_KEYWORDS + [
    "автоматизац", "автоматизир", "нейросет", " бот", "-бот", " ии ", "ии-", "gpt", "openai", "llm",
    "automation", "automate", " ai ", "ai-", "workflow",
]

# Мусульманская ниша — такие заказы помечаем 🕌 и ставим первыми.
HALAL_KEYWORDS = [
    "ислам", "мусульман", "халяль", "халал", "мечет", "намаз", "коран", "хиджаб", "умра", "хадж",
    "islam", "muslim", "halal", "mosque", "quran", "hijab", "umrah", "modest",
]

# Категории, заказы из которых НЕ показываем никогда (харам-ниши).
EXCLUDE_KEYWORDS = [
    # азартные игры / ставки
    "казино", "ставки на спорт", "ставок на", "букмекер", "беттинг", "азартн",
    "покер", "слот-автомат", "игровой автомат", "рулетк", "лотере", "тотализатор",
    "casino", "gambling", "betting", "bookmaker", "sportsbook", "poker", "slot machine", "lottery",
    # финансовые/риба-ниши
    "форекс", "бинарные опцион", "бинарный опцион", "микрозайм", "ломбард", "кредитная организация",
    "forex", "binary options", "microloan", "pawnshop",
    # алкоголь
    "алкогол", "спиртн", "винодел", "пивовар", "ликёр", "ликер", "виски", "водка",
    "alcohol", "liquor", "whiskey", "vodka", "brewery", "distillery",
    # свинина
    "свинин", "бекон", "ветчин",
    "pork", "bacon", " ham ",
    # банки
    "банк", "bank",
]

FREELANCER_QUERIES = [
    "n8n", "make.com", "zapier", "telegram bot", "ai agent",
    "social media automation", "auto posting", "chatbot",
]

REQUEST_DELAY_SEC = 1.5


def has_any(text, keywords):
    return any(kw in text for kw in keywords)


def clean(text):
    """Убирает HTML-теги и сущности из описания заказа."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def make_lead(source, key, title, url, snippet, budget, lang):
    return {
        "source": source, "key": key, "title": title, "url": url,
        "snippet": snippet, "budget": budget, "lang": lang,
    }


FL_BUDGET_RE = re.compile(r"\s*\(Бюджет:\s*([\d\s]+)[^)]*\)")


def fetch_fl():
    """RSS последних заказов FL.ru. Бюджет FL пишет прямо в заголовке."""
    resp = requests.get("https://www.fl.ru/rss/all.xml", headers=HEADERS, timeout=20)
    resp.raise_for_status()
    leads = []
    for item in ET.fromstring(resp.content).iter("item"):
        title = html.unescape(item.findtext("title") or "")
        budget = ""
        m = FL_BUDGET_RE.search(title)
        if m:
            amount = int(re.sub(r"\D", "", m.group(1)) or 0)
            if amount and amount < MIN_BUDGET_RUB:
                continue
            budget = f"{amount:,} ₽".replace(",", " ")
            title = FL_BUDGET_RE.sub("", title)
        title = re.sub(r"\s*\(для всех\)", "", title).strip()
        category = item.findtext("category") or ""
        link = item.findtext("link") or ""
        leads.append(make_lead(
            "FL.ru", f"fl:{link}", title, link,
            clean(f"[{category}] {item.findtext('description') or ''}"), budget, "ru",
        ))
    return leads


def fetch_freelancer():
    """Открытый API Freelancer.com — без ключа."""
    leads = []
    for query in FREELANCER_QUERIES:
        resp = requests.get(
            "https://www.freelancer.com/api/projects/0.1/projects/active/",
            params={"query": query, "limit": 20, "full_description": "true"},
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        for p in resp.json()["result"]["projects"]:
            b = p.get("budget") or {}
            cur = p.get("currency") or {}
            top = b.get("maximum") or b.get("minimum") or 0
            if top * float(cur.get("exchange_rate") or 1) < MIN_BUDGET_USD:
                continue
            budget = f"{b.get('minimum') or 0:.0f}–{top:.0f} {cur.get('code', '')}"
            leads.append(make_lead(
                "Freelancer", f"fr:{p['id']}", p["title"],
                f"https://www.freelancer.com/projects/{p['seo_url']}",
                clean(p.get("description") or p.get("preview_description")), budget, "en",
            ))
        time.sleep(REQUEST_DELAY_SEC)
    return leads


SOURCES = [("FL.ru", fetch_fl), ("Freelancer", fetch_freelancer)]
# FL.ru отдаёт 403 серверам GitHub, поэтому его проверяет домашний ПК
# (run_lead_finder_local.cmd), а Actions — только Freelancer. Пусто = все площадки.
_only = {s.strip() for s in os.getenv("LEAD_SOURCES", "").split(",") if s.strip()}
if _only:
    SOURCES = [src for src in SOURCES if src[0] in _only]


def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_seen(seen):
    # Список, а не set: обрезаем самые старые, а не случайные ключи.
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen[-MAX_SEEN:], f, ensure_ascii=False, indent=2)


CONTACT_HANDLE = os.getenv("AUTHOR_TELEGRAM", "https://t.me/Halalaifreya")

PITCH_TEMPLATES = {
    "ru": (
        "✍️ Черновик отклика на русские заказы (подправь под задачу):\n"
        "«Здравствуйте! Делаю ИИ-автоматизации под ключ: автопостинг в Telegram/Threads/YouTube, "
        "Telegram-боты для заявок, связки с нейросетями. Мои каналы уже месяцами публикуются "
        "полностью автоматически — могу показать. Расскажите подробнее о задаче, предложу решение "
        f"и срок. Связь: {CONTACT_HANDLE}»"
    ),
    "en": (
        "✍️ Черновик отклика на английские заказы (Freelancer):\n"
        "\"Hi! I build AI automations end-to-end: auto-posting to Telegram/Threads/YouTube, "
        "Telegram bots for leads, LLM-powered workflows. My own channels have been running fully "
        "automated for months — happy to show them. Could you share more details? "
        f"I'll propose a solution and timeline. Contact: {CONTACT_HANDLE}\""
    ),
}


def format_lead(lead):
    mark = "🕌 " if lead["halal"] else ""
    text = f"{mark}• [{lead['source']}] {lead['title']}"
    if lead["budget"]:
        text += f" — {lead['budget']}"
    text += f"\n{lead['url']}"
    if lead["snippet"]:
        text += f"\n{lead['snippet'][:220]}"
    return text


def send_digest(leads, skipped):
    """Шлёт находки пачками, чтобы не упереться в лимит длины сообщения Telegram."""
    header = f"🤖 Новые заказы на автоматизацию: {len(leads)}"
    if skipped:
        header += f" (ещё {skipped} не влезли — будут в следующий раз)"
    chunk = header + "\n\n"
    for lead in leads:
        piece = format_lead(lead) + "\n\n"
        if len(chunk) + len(piece) > 3500:
            notify(chunk)
            chunk = ""
        chunk += piece
    for lang in sorted({l["lang"] for l in leads}, reverse=True):
        piece = PITCH_TEMPLATES[lang] + "\n\n"
        if len(chunk) + len(piece) > 3500:
            notify(chunk)
            chunk = ""
        chunk += piece
    if chunk.strip():
        notify(chunk)


def run():
    seen = load_seen()
    seen_set = set(seen)
    found = []
    failed = []

    for name, fetch in SOURCES:
        try:
            raw = fetch()
        except Exception as e:
            print(f"[lead_finder] {name}: не удалось получить заказы — {e}")
            failed.append(name)
            continue
        matched = 0
        for lead in raw:
            if lead["key"] in seen_set:
                continue
            title = f" {lead['title']} ".lower()
            text = f" {lead['title']} {lead['snippet']} ".lower()
            # Freelancer ищет по описанию сам и приносит много смежного (реклама, SEO) —
            # там верим только названию.
            relevant = has_any(title, TITLE_KEYWORDS) or (
                lead["source"] != "Freelancer" and has_any(text, STRONG_KEYWORDS)
            )
            if not relevant or has_any(text, EXCLUDE_KEYWORDS):
                continue
            lead["halal"] = has_any(text, HALAL_KEYWORDS)
            seen_set.add(lead["key"])
            found.append(lead)
            matched += 1
        print(f"[lead_finder] {name}: просмотрено {len(raw)}, подходящих новых {matched}")

    # Мусульманская ниша — первой, затем русскоязычные площадки.
    found.sort(key=lambda l: (not l["halal"], l["lang"] != "ru"))
    to_send, rest = found[:MAX_LEADS_PER_RUN], found[MAX_LEADS_PER_RUN:]
    # Не влезшие в сообщение не помечаем просмотренными — придут следующим запуском.
    rest_keys = {l["key"] for l in rest}
    seen.extend(l["key"] for l in found if l["key"] not in rest_keys)
    save_seen(seen)

    if to_send:
        send_digest(to_send, len(rest))
        print(f"[lead_finder] Отправлено находок: {len(to_send)}")
    else:
        print("[lead_finder] Новых заказов не найдено.")

    if len(failed) == len(SOURCES):
        alert_fail("lead_finder", "Ни одна площадка не ответила: " + ", ".join(failed))


if __name__ == "__main__":
    run()
