# lead_finder.py — ищет свежие заказы на ИИ-автоматизацию (автопостинг, Telegram-боты,
# n8n/Make/Zapier, ИИ-агенты, чат-боты) и присылает находки в Telegram с черновиком отклика.
# Источники читаются напрямую, без поисковика: DuckDuckGo с 18.09.2026 блокирует
# GitHub Actions целиком, а ленты площадок отдают заказы без блокировок.
# Kwork убран 19.09.2026: Kwork.ru закрывает продажи для не-граждан РФ и выводит
# деньги только на российские карты — заказы оттуда владелице бесполезны.
# FL.ru убран 24.09.2026 по той же причине: платные отклики — только с российской карты.
#   • Freelancer.com — открытый API поиска проектов (международные заказы, en).
#   • Reddit — RSS разделов, где заказчики ищут исполнителей (r/forhire, r/n8n и др.).
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
    " crm", "hubspot", "amocrm", "bitrix", "pipedrive",
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

# Не наш профиль, хотя в названии мелькает «AI»: разметка данных, обучение ИИ
# носителями языка, переводы. Проверяем только название — в описании эти слова
# встречаются и в подходящих заказах («no translation needed»).
OFF_PROFILE_TITLE_KEYWORDS = [
    "bilingual", "native speaker", "speakers", "translator", "translation", "transcri",
    "annotat", "labeling", "labelling", "ai training", "ai trainer", "rlhf",
    "переводчик", "перевод текст", "транскриб", "разметк",
]

# Reddit пишет цену прямо в названии («- $25»). Если все суммы ниже порога —
# заказ того не стоит: на такие за минуты приходят десятки откликов.
MIN_REDDIT_USD = 50
DOLLAR_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k\b)?(\s*(?:/|per)\s*(?:h|hr|hour))?", re.I)


def title_budget_usd(title):
    """Сумма за проект из названия Reddit; None — суммы нет или она почасовая."""
    amounts = []
    for m in DOLLAR_RE.finditer(title):
        if m.group(3):
            return None
        amounts.append(float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1))
    return max(amounts) if amounts else None


FREELANCER_QUERIES = [
    "n8n", "make.com", "zapier", "telegram bot", "ai agent",
    "social media automation", "auto posting", "chatbot",
    "crm integration", "hubspot",
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
            lead = make_lead(
                "Freelancer", f"fr:{p['id']}", p["title"],
                f"https://www.freelancer.com/projects/{p['seo_url']}",
                clean(p.get("description") or p.get("preview_description")), budget, "en",
            )
            lead["raw"] = p  # negotiator.py делает отклик по id, валюте и вилке бюджета
            leads.append(lead)
        time.sleep(REQUEST_DELAY_SEC)
    return leads


# Разделы, где заказчики ищут исполнителей. Одним запросом через «+»: по одному
# Reddit уже на третьем запросе отвечает 429 (слишком часто).
REDDIT_SUBS = "forhire+hiring+slavelabour+freelance_forhire+n8n+automation+zapier+Automate"
REDDIT_REQUEST_RE = re.compile(r"\[(hiring|task)\]|\bhiring\b|looking for|need (a|an|someone)|\bpaid\b", re.I)
REDDIT_OFFER_RE = re.compile(r"\[(for hire|offer)\]", re.I)
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def fetch_reddit():
    """RSS свежих постов из разделов-заказов Reddit. Оставляем только запросы
    заказчиков — объявления «[For Hire]»/«[Offer]» пишут сами исполнители."""
    resp = requests.get(f"https://www.reddit.com/r/{REDDIT_SUBS}/new/.rss?limit=100",
                        headers=HEADERS, timeout=20)
    resp.raise_for_status()
    leads = []
    for e in ET.fromstring(resp.content).findall("a:entry", ATOM):
        title = html.unescape(e.findtext("a:title", "", ATOM)).strip()
        if REDDIT_OFFER_RE.search(title) or not REDDIT_REQUEST_RE.search(title):
            continue
        top = title_budget_usd(title)
        if top is not None and top < MIN_REDDIT_USD:
            continue
        link = e.find("a:link", ATOM)
        url = link.get("href") if link is not None else ""
        sub = (e.find("a:category", ATOM).get("term") if e.find("a:category", ATOM) is not None else "")
        leads.append(make_lead(
            f"Reddit r/{sub}", f"reddit:{e.findtext('a:id', '', ATOM)}", title, url,
            clean(e.findtext("a:content", "", ATOM)).replace("submitted by", "").strip(),
            f"${top:,.0f}" if top else "", "en",
        ))
    return leads


SOURCES = [("Freelancer", fetch_freelancer), ("Reddit", fetch_reddit)]
# Actions проверяет только Reddit: Freelancer сам ведёт negotiator.py. Пусто = все площадки.
_only = {s.strip() for s in os.getenv("LEAD_SOURCES", "").split(",") if s.strip()}
if _only:
    SOURCES = [src for src in SOURCES if src[0] in _only]


def is_relevant(lead):
    """Заказ на автоматизацию и не из харам-ниши. Заодно ставит lead["halal"]."""
    title = f" {lead['title']} ".lower()
    text = f" {lead['title']} {lead['snippet']} ".lower()
    # Freelancer ищет по описанию сам и приносит много смежного (реклама, SEO) —
    # там верим только названию.
    relevant = has_any(title, TITLE_KEYWORDS) or (
        lead["source"] != "Freelancer" and has_any(text, STRONG_KEYWORDS)
    )
    if not relevant or has_any(text, EXCLUDE_KEYWORDS) or has_any(title, OFF_PROFILE_TITLE_KEYWORDS):
        return False
    lead["halal"] = has_any(text, HALAL_KEYWORDS)
    return True


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
# Ссылка на готовую работу (канал с автопостингом) — вставляется в отклики на языке заказа.
PORTFOLIO_URLS = {
    "en": os.getenv("PORTFOLIO_URL_EN", "").strip() or "https://youtube.com/@easy_arabic-o3m",
    "ru": os.getenv("PORTFOLIO_URL_RU", "").strip() or "https://youtube.com/@arabicllanguage",
}

PITCH_TEMPLATES = {
    "ru": (
        "✍️ Черновик отклика на русские заказы (подправь под задачу):\n"
        "«Здравствуйте! Делаю ИИ-автоматизации под ключ: автопостинг в Telegram/Threads/YouTube, "
        "Telegram-боты для заявок, связки с нейросетями. Мои каналы уже месяцами публикуются "
        "полностью автоматически — могу показать"
        + (f": {PORTFOLIO_URLS['ru']}" if PORTFOLIO_URLS["ru"] else "")
        + f". Расскажите подробнее о задаче, предложу решение и срок. Связь: {CONTACT_HANDLE}»"
    ),
    "en": (
        "✍️ Черновик отклика на английские заказы (Freelancer, Reddit):\n"
        "\"Hi! I build AI automations end-to-end: auto-posting to Telegram/Threads/YouTube, "
        "Telegram bots for leads, LLM-powered workflows. My own channels have been running fully "
        "automated for months"
        + (f" — see {PORTFOLIO_URLS['en']}" if PORTFOLIO_URLS["en"] else " — happy to show them")
        + ". Could you share more details? "
        f"I'll propose a solution and timeline. Contact: {CONTACT_HANDLE}\""
    ),
}


# Личный отклик под каждый заказ пишет Claude Haiku: шаблон одинаковый для всех,
# и заказчики его пролистывают. Платно, но копейки (~$0.002 за отклик); лимит на
# запуск — чтобы не тратиться на хвост списка. Нет ключа или ошибка — шаблон.
PITCH_MODEL = os.getenv("LEAD_PITCH_MODEL", "claude-haiku-4-5")
MAX_PITCHES_PER_RUN = int(os.getenv("LEAD_MAX_PITCHES_PER_RUN", "6"))
PROFILE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "negotiator_profile.md")

PITCH_SCHEMA = {
    "type": "object",
    "properties": {
        "fit": {"type": "boolean"},
        "reason_ru": {"type": "string"},
        "pitch": {"type": "string"},
    },
    "required": ["fit", "reason_ru", "pitch"],
    "additionalProperties": False,
}


def write_pitches(leads):
    """Добавляет lead["pitch"] (или lead["unfit"]) первым MAX_PITCHES_PER_RUN заказам."""
    if not os.getenv("ANTHROPIC_API_KEY") or MAX_PITCHES_PER_RUN <= 0:
        return
    try:
        import anthropic
        client = anthropic.Anthropic()
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            profile = f.read()
    except Exception as e:
        print(f"[lead_finder] Личные отклики недоступны — {e}")
        return
    system = (
        "You write short replies to freelance job posts on behalf of a freelance developer "
        "of AI automations. Her profile (in Russian) is below: services, prices and rules, "
        "including Islamic rules that are never negotiable. The post is from Reddit, "
        "NOT Freelancer.com, so the Freelancer rule about not sharing contacts does not apply "
        "here: end the reply with the contact line given in the task.\n"
        "fit = true only if the job is covered by her services and allowed by all her rules; "
        "otherwise fit = false, pitch = \"\" and explain why in reason_ru (one sentence).\n"
        "If fit: write the pitch in the language of the post. 4–6 sentences: "
        "show you understood the task (mention 1–2 concrete details from the post), say how "
        "you would build it, mention one of her relevant own projects, ask 1 clarifying "
        "question, then the contact line. No 'Dear Sir', no placeholders, never invent "
        "experience, reviews or links that are not given.\n\n=== PROFILE ===\n" + profile
    )
    for lead in leads[:MAX_PITCHES_PER_RUN]:
        task = (f"Source: {lead['source']}\nTitle: {lead['title']}\nBudget: {lead['budget'] or 'not stated'}\n"
                f"Post:\n{lead['snippet'][:3000]}\n\nContact: {CONTACT_HANDLE}")
        portfolio = PORTFOLIO_URLS.get(lead["lang"])
        if portfolio:
            task += f"\nPortfolio (live example): {portfolio}"
        try:
            resp = client.messages.create(
                model=PITCH_MODEL, max_tokens=1500,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": task}],
                output_config={"format": {"type": "json_schema", "schema": PITCH_SCHEMA}},
            )
            data = json.loads(next(b.text for b in resp.content if b.type == "text"))
        except Exception as e:
            print(f"[lead_finder] Отклик для «{lead['title'][:50]}» не написан — {e}")
            continue
        if data["fit"] and data["pitch"].strip():
            lead["pitch"] = data["pitch"].strip()
        else:
            lead["unfit"] = data["reason_ru"].strip()


def format_lead(lead):
    mark = "🕌 " if lead["halal"] else ""
    text = f"{mark}• [{lead['source']}] {lead['title']}"
    if lead["budget"]:
        text += f" — {lead['budget']}"
    text += f"\n{lead['url']}"
    if lead["snippet"]:
        text += f"\n{lead['snippet'][:220]}"
    if lead.get("pitch"):
        text += f"\n✍️ Отклик (скопируй и отправь):\n{lead['pitch']}"
    elif lead.get("unfit"):
        text += f"\n⚠️ Похоже, не твой профиль: {lead['unfit']}"
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
    # Общий шаблон — только для заказов, которым личный отклик не достался.
    for lang in sorted({l["lang"] for l in leads if "pitch" not in l and "unfit" not in l}, reverse=True):
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
            if lead["key"] in seen_set or not is_relevant(lead):
                continue
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
        write_pitches(to_send)
        send_digest(to_send, len(rest))
        print(f"[lead_finder] Отправлено находок: {len(to_send)}")
    else:
        print("[lead_finder] Новых заказов не найдено.")

    if SOURCES and len(failed) == len(SOURCES):
        alert_fail("lead_finder", "Ни одна площадка не ответила: " + ", ".join(failed))


if __name__ == "__main__":
    run()
