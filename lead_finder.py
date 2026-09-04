# lead_finder.py — ищет реальные заказы на разработку сайтов (любая ниша, кроме харам)
# и присылает новые находки в Telegram. Источник — Google Custom Search API,
# с резервом на открытый HTML-поиск DuckDuckGo.
import time

import requests
from bs4 import BeautifulSoup

from paths import dpath
from telegram_notify import notify, alert_fail
import json
import os

SEEN_FILE = dpath("seen_leads.json")
MAX_SEEN = 1000

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# Категории, заказы из которых НЕ показываем никогда (харам-ниши).
# Проверяются и в самом запросе (минус-слова), и повторно в тексте результата.
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
    # арабский (Персидский залив)
    "قمار", "كازينو", "مراهنات", "رهان", "خمر", "كحول", "خنزير", "بنك",
]

EXCLUDE_QUERY_SUFFIX = (
    " -казино -ставки -букмекер -покер -алкоголь -пиво -вино -свинина -бекон -банк -кредит -ломбард -forex -casino -gambling"
)


def is_forbidden(*parts):
    text = " ".join(parts).lower()
    return any(kw in text for kw in EXCLUDE_KEYWORDS)


# Запросы нацелены на людей/организации, которые ПРЯМО СЕЙЧАС просят сделать сайт —
# это реальные заказы, а не холодные лиды. Каждый запрос помечен языком (ru/en/ar) —
# на нём же готовится черновик предложения для заказчика.
GENERAL_QUERIES = [
    ('"нужен сайт" заказ' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('"требуется сайт" бизнес' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('"ищу разработчика" сайт' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('"ищу веб-разработчика"' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('"требуется веб-разработчик"' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('"нужен лендинг"' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('"нужен интернет-магазин"' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('"создать сайт" под ключ заказ' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('site:kwork.ru сайт заказ' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('site:kwork.ru лендинг заказ' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('site:fl.ru сайт заказ' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('site:fl.ru лендинг заказ' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('site:youdo.com сайт разработка заказ' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('site:freelance.ru сайт заказ' + EXCLUDE_QUERY_SUFFIX, "ru"),
    ('site:weblancer.net сайт заказ' + EXCLUDE_QUERY_SUFFIX, "ru"),
]

HALAL_QUERIES = [
    ('site:kwork.ru сайт мечеть', "ru"),
    ('site:kwork.ru сайт ислам', "ru"),
    ('site:kwork.ru сайт халяль', "ru"),
    ('site:fl.ru сайт мечеть', "ru"),
    ('site:fl.ru сайт ислам', "ru"),
    ('site:youdo.com сайт мечеть', "ru"),
    ('site:youdo.com сайт халяль', "ru"),
    ('site:freelance.ru сайт мечеть', "ru"),
    ('"нужен сайт" мечеть', "ru"),
    ('"нужен сайт" халяль', "ru"),
    ('"нужен сайт" ислам магазин', "ru"),
    ('"требуется сайт" мусульман', "ru"),
    ('"ищу разработчика" мечеть сайт', "ru"),
    ('"ищу разработчика" халяль сайт', "ru"),
    ('"создать сайт" исламский центр', "ru"),
    ('"создать сайт" халяль магазин', "ru"),
    ('upwork "halal" website developer needed', "en"),
    ('upwork "islamic" website developer needed', "en"),
    ('freelancer.com "halal" website', "en"),
    ('freelancer.com "mosque" website', "en"),
]

# Англоязычные площадки в целом — любая ниша, кроме харам.
INTL_QUERIES = [
    ('"looking for a web developer"' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"need a website built"' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"need a website" freelance' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"hiring a web developer"' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"website developer needed"' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('upwork "website developer" needed' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('upwork "landing page" needed' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('freelancer.com "website" project needed' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('site:reddit.com/r/forhire "website"' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('site:reddit.com/r/forhire "landing page"' + EXCLUDE_QUERY_SUFFIX, "en"),
]

# Персидский залив — англо- и арабоязычные объявления (ОАЭ, Саудовская Аравия,
# Катар, Кувейт, Бахрейн, Оман).
GULF_QUERIES = [
    ('"need a website" Dubai' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"need a website" UAE' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"web developer needed" Saudi Arabia' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"website developer" Qatar hiring' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"need a website" Kuwait' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"need a website" Bahrain' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"need a website" Oman' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('مطلوب مصمم مواقع' + EXCLUDE_QUERY_SUFFIX, "ar"),
    ('نحتاج موقع الكتروني' + EXCLUDE_QUERY_SUFFIX, "ar"),
]

# Европа и США — общий поиск заказов на сайты.
EUROPE_US_QUERIES = [
    ('"need a website" small business USA' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"looking for a website developer" UK' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('"web developer needed" Europe freelance' + EXCLUDE_QUERY_SUFFIX, "en"),
    ('site:reddit.com/r/slavelabour "website"' + EXCLUDE_QUERY_SUFFIX, "en"),
]

QUERIES = GENERAL_QUERIES + HALAL_QUERIES + INTL_QUERIES + GULF_QUERIES + EUROPE_US_QUERIES

REQUEST_DELAY_SEC = 2

GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "")


def search_google_cse(query, max_results=6):
    """Поиск через Google Custom Search JSON API (бесплатно до 100 запросов/день).
    Требует GOOGLE_CSE_API_KEY и GOOGLE_CSE_CX — см. README-инструкцию в repo."""
    resp = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": GOOGLE_CSE_API_KEY,
            "cx": GOOGLE_CSE_CX,
            "q": query,
            "num": min(max_results, 10),
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("items", [])[:max_results]:
        title = item.get("title", "")
        url = item.get("link", "")
        snippet = item.get("snippet", "")
        if url:
            results.append((title, url, snippet))
    return results


def search_duckduckgo(query, max_results=6):
    """Резервный поиск через html.duckduckgo.com — без ключей, но DDG часто
    блокирует автоматические запросы ("anomaly detected"), особенно с CI-раннеров.
    Используется только если не заданы ключи Google CSE."""
    resp = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for block in soup.select("div.result")[:max_results]:
        link = block.select_one("a.result__a")
        snippet_el = block.select_one("a.result__snippet") or block.select_one(".result__snippet")
        if not link or not link.get("href"):
            continue
        title = link.get_text(strip=True)
        url = link["href"]
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
        results.append((title, url, snippet))
    return results


def search(query, max_results=6):
    if GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX:
        return search_google_cse(query, max_results)
    return search_duckduckgo(query, max_results)


def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_seen(seen):
    trimmed = list(seen)[-MAX_SEEN:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


CONTACT_HANDLE = os.getenv("AUTHOR_TELEGRAM", "https://t.me/Halalaifreya")

PITCH_TEMPLATES = {
    "ru": (
        "Черновик ответа (просто скопируй и отправь, если подходит):\n"
        "«Здравствуйте! Увидел(а) ваш запрос на разработку сайта. Делаю сайты и "
        "лендинги под ключ, есть портфолио и опыт. Расскажите подробнее о задаче "
        f"и сроках — подготовлю предложение. Написать можно сюда: {CONTACT_HANDLE}»"
    ),
    "en": (
        "Draft reply (copy-paste if it fits, edit as needed):\n"
        "\"Hi! I saw your post about needing a website. I build custom websites "
        "and landing pages, happy to share my portfolio and a quick quote. Could "
        f"you share more about the project and timeline? You can reach me here: {CONTACT_HANDLE}\""
    ),
    "ar": (
        "مسودة رد (انسخ والصق إذا كانت مناسبة):\n"
        "«مرحباً! رأيت طلبكم لتصميم موقع إلكتروني. أقوم بتصميم مواقع وصفحات هبوط "
        "احترافية، ولدي أعمال سابقة يمكن عرضها. هل يمكنكم إخباري بتفاصيل أكثر عن "
        f"المشروع والمدة الزمنية؟ يمكنكم التواصل معي هنا: {CONTACT_HANDLE}»"
    ),
}


def format_lead(title, url, snippet, lang):
    text = f"• {title}\n{url}"
    if snippet:
        text += f"\n{snippet[:180]}"
    text += "\n" + PITCH_TEMPLATES.get(lang, PITCH_TEMPLATES["en"])
    return text


def send_digest(leads):
    """Шлёт находки пачками, чтобы не упереться в лимит длины сообщения Telegram."""
    header = f"🕌 Найдено новых заказов: {len(leads)}\n"
    chunk = header
    for lead in leads:
        piece = format_lead(*lead) + "\n\n"
        if len(chunk) + len(piece) > 3500:
            notify(chunk)
            chunk = ""
        chunk += piece
    if chunk.strip():
        notify(chunk)


def run():
    seen = load_seen()
    new_leads = []
    failures = 0

    for query, lang in QUERIES:
        try:
            for title, url, snippet in search(query):
                if url in seen:
                    continue
                seen.add(url)
                if is_forbidden(title, url, snippet):
                    continue
                new_leads.append((title, url, snippet, lang))
        except Exception as e:
            failures += 1
            print(f"[lead_finder] Запрос не удался: {query!r} — {e}")
        time.sleep(REQUEST_DELAY_SEC)

    save_seen(seen)

    if new_leads:
        send_digest(new_leads)
        print(f"[lead_finder] Отправлено находок: {len(new_leads)}")
    else:
        print("[lead_finder] Новых заказов не найдено.")

    if failures == len(QUERIES):
        reason = (
            "Все запросы упали — проверь квоту Google CSE (100/день) или ключи GOOGLE_CSE_API_KEY/GOOGLE_CSE_CX."
            if GOOGLE_CSE_API_KEY
            else "Все запросы упали — DuckDuckGo заблокировал IP. Настрой GOOGLE_CSE_API_KEY/GOOGLE_CSE_CX для надёжного поиска."
        )
        alert_fail("lead_finder", reason)


if __name__ == "__main__":
    run()
