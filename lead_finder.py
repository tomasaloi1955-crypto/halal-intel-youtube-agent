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
]

EXCLUDE_QUERY_SUFFIX = (
    " -казино -ставки -букмекер -покер -алкоголь -пиво -вино -свинина -бекон -банк -кредит -ломбард -forex -casino -gambling"
)


def is_forbidden(*parts):
    text = " ".join(parts).lower()
    return any(kw in text for kw in EXCLUDE_KEYWORDS)


# Запросы нацелены на людей/организации, которые ПРЯМО СЕЙЧАС просят сделать сайт —
# это реальные заказы, а не холодные лиды. Общие — любая ниша (кроме харам, см. фильтр
# выше), плюс отдельно халяль/исламская ниша, где у Халяль Интеллидженс есть репутация.
GENERAL_QUERIES = [
    '"нужен сайт" заказ' + EXCLUDE_QUERY_SUFFIX,
    '"требуется сайт" бизнес' + EXCLUDE_QUERY_SUFFIX,
    '"ищу разработчика" сайт' + EXCLUDE_QUERY_SUFFIX,
    '"ищу веб-разработчика"' + EXCLUDE_QUERY_SUFFIX,
    '"требуется веб-разработчик"' + EXCLUDE_QUERY_SUFFIX,
    '"нужен лендинг"' + EXCLUDE_QUERY_SUFFIX,
    '"нужен интернет-магазин"' + EXCLUDE_QUERY_SUFFIX,
    '"создать сайт" под ключ заказ' + EXCLUDE_QUERY_SUFFIX,
    'site:kwork.ru сайт заказ' + EXCLUDE_QUERY_SUFFIX,
    'site:kwork.ru лендинг заказ' + EXCLUDE_QUERY_SUFFIX,
    'site:fl.ru сайт заказ' + EXCLUDE_QUERY_SUFFIX,
    'site:fl.ru лендинг заказ' + EXCLUDE_QUERY_SUFFIX,
    'site:youdo.com сайт разработка заказ' + EXCLUDE_QUERY_SUFFIX,
    'site:freelance.ru сайт заказ' + EXCLUDE_QUERY_SUFFIX,
    'site:weblancer.net сайт заказ' + EXCLUDE_QUERY_SUFFIX,
    'upwork "website developer" needed' + EXCLUDE_QUERY_SUFFIX,
    'upwork "landing page" needed' + EXCLUDE_QUERY_SUFFIX,
    'freelancer.com "website" project needed' + EXCLUDE_QUERY_SUFFIX,
]

HALAL_QUERIES = [
    'site:kwork.ru сайт мечеть',
    'site:kwork.ru сайт ислам',
    'site:kwork.ru сайт халяль',
    'site:fl.ru сайт мечеть',
    'site:fl.ru сайт ислам',
    'site:youdo.com сайт мечеть',
    'site:youdo.com сайт халяль',
    'site:freelance.ru сайт мечеть',
    '"нужен сайт" мечеть',
    '"нужен сайт" халяль',
    '"нужен сайт" ислам магазин',
    '"требуется сайт" мусульман',
    '"ищу разработчика" мечеть сайт',
    '"ищу разработчика" халяль сайт',
    '"создать сайт" исламский центр',
    '"создать сайт" халяль магазин',
    'upwork "halal" website developer needed',
    'upwork "islamic" website developer needed',
    'freelancer.com "halal" website',
    'freelancer.com "mosque" website',
]

QUERIES = GENERAL_QUERIES + HALAL_QUERIES

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


def format_lead(title, url, snippet):
    text = f"• {title}\n{url}"
    if snippet:
        text += f"\n{snippet[:180]}"
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

    for query in QUERIES:
        try:
            for title, url, snippet in search(query):
                if url in seen:
                    continue
                seen.add(url)
                if is_forbidden(title, url, snippet):
                    continue
                new_leads.append((title, url, snippet))
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
