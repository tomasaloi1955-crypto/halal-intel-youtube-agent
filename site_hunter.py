# site_hunter.py — ищет в Google Картах компании Казахстана БЕЗ своего сайта и
# присылает в Telegram карточки для холодного звонка: телефон, адрес, рейтинг,
# короткий скрипт разговора и готовое сообщение в WhatsApp после звонка.
#
# Как и channel_hunter, агент сам никому не звонит и не пишет — только находит и
# готовит. Звонит владелица.
#
# Источник: Google Places API (New), Text Search — «стоматология в Алматы» и т. п.
# У каждой найденной точки Google отдаёт поле websiteUri; нет его (или вместо сайта
# стоит Instagram / 2ГИС / WhatsApp) — значит, своего сайта у компании нет.
# Ключ: GOOGLE_MAPS_API_KEY (console.cloud.google.com → Places API (New)).
import json
import os
import re
from datetime import datetime
from urllib.parse import quote

import requests

from paths import dpath
from telegram_notify import notify, alert_fail

SEEN_FILE = dpath("seen_places.json")
QUERY_POS_KEY = "_query_pos"
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
CARDS_PER_RUN = int(os.getenv("SITE_CARDS", "15"))
# Один запрос = до 20 компаний. Бесплатно Google даёт 1000 таких запросов в месяц,
# 30 в день укладываются с запасом.
MAX_REQUESTS_PER_RUN = int(os.getenv("SITE_REQUESTS", "30"))
MIN_REVIEWS = 3               # совсем без отзывов — часто закрытые или «мёртвые» точки

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.nationalPhoneNumber", "places.internationalPhoneNumber", "places.websiteUri",
    "places.rating", "places.userRatingCount", "places.businessStatus",
    "places.primaryTypeDisplayName", "places.googleMapsUri", "nextPageToken",
])

CITIES = [
    "Алматы", "Астана", "Шымкент", "Караганда", "Актобе", "Тараз", "Павлодар",
    "Усть-Каменогорск", "Семей", "Атырау", "Костанай", "Кызылорда", "Уральск",
    "Петропавловск", "Актау", "Туркестан", "Талдыкорган", "Кокшетау",
]
# Ниши, где сайт реально приносит клиентов, а у владельцев он часто отсутствует.
CATEGORIES = [
    "стоматология", "салон красоты", "автосервис", "барбершоп", "ремонт квартир",
    "мебель на заказ", "клининговая компания", "фитнес клуб", "детский развивающий центр",
    "учебный центр", "юридические услуги", "бухгалтерские услуги", "ветеринарная клиника",
    "натяжные потолки", "окна пвх", "кафе", "доставка еды", "цветочный магазин",
    "ателье", "шиномонтаж", "автомойка", "массажный салон", "косметология",
    "туристическое агентство", "грузоперевозки", "строительная компания",
    "магазин стройматериалов", "типография", "фотостудия", "языковые курсы",
    "медицинский центр", "оптика", "ремонт телефонов", "химчистка", "свадебный салон",
]
QUERIES = [f"{cat} {city}" for city in CITIES for cat in CATEGORIES]

# «Сайт», который на деле не сайт: соцсеть, мессенджер, карточка в справочнике.
NOT_A_SITE = (
    "instagram.com", "facebook.com", "wa.me", "whatsapp.com", "t.me", "telegram.me",
    "vk.com", "tiktok.com", "2gis.", "youtube.com", "linktr.ee", "taplink",
    "google.com", "g.page", "business.site", "kaspi.kz", "olx.kz", "satu.kz",
)
# Сети и госорганы — им звонить бессмысленно.
SKIP_NAME_WORDS = (
    "акимат", "гкп", "кгп", "ргп", "коммунальн", "государствен", "поликлиника №",
    "kaspi", "halyk", "magnum", "small", "toyota", "kia ", "hyundai",
)


def load_state():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def search(query, page_token=None):
    """Одна страница выдачи Google Карт (до 20 мест) и токен следующей."""
    body = {"textQuery": query, "languageCode": "ru", "regionCode": "KZ", "pageSize": 20}
    if page_token:
        body["pageToken"] = page_token
    resp = requests.post(
        SEARCH_URL, json=body, timeout=30,
        headers={"X-Goog-Api-Key": API_KEY, "X-Goog-FieldMask": FIELDS},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Google Places {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data.get("places", []), data.get("nextPageToken")


def site_status(website):
    """None — сайта нет; 'social' — вместо сайта соцсеть/справочник; 'site' — есть сайт."""
    if not website:
        return None
    low = website.lower()
    return "social" if any(s in low for s in NOT_A_SITE) else "site"


def phone_digits(place):
    """+7 701 123 45 67 → 77011234567 (или пустая строка)."""
    raw = place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber") or ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits if len(digits) == 11 and digits.startswith("7") else ""


MOBILE_CODES = {"700", "701", "702", "705", "706", "707", "708", "747",
                "771", "775", "776", "777", "778"}


def is_mobile(digits):
    """Казахстанский мобильный (+7 701…, +7 747… и т. п.) — на нём есть WhatsApp.
    Городские тоже начинаются на 7 (Алматы — 727, Астана — 717), поэтому по коду."""
    return digits[1:4] in MOBILE_CODES


def pretty_phone(digits):
    return f"+7 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:11]}"


def score(place, status):
    """Чем выше, тем вероятнее, что у компании есть деньги и сайт ей нужен."""
    reviews = place.get("userRatingCount") or 0
    points = min(reviews, 300) // 5          # много отзывов — живой бизнес с клиентами
    if (place.get("rating") or 0) >= 4.5:
        points += 10                         # хорошая репутация, которую не видно в поиске
    if status == "social":
        points += 15                         # уже вкладывается в продвижение — «созрел»
    if is_mobile(phone_digits(place)):
        points += 10                         # мобильный — скорее всего, ответит сам владелец
    return points


def collect(state, start):
    """Идёт по запросам с позиции start, пока не наберёт кандидатов или лимит запросов."""
    candidates, requests_done, pos = [], 0, start
    while requests_done < MAX_REQUESTS_PER_RUN and len(candidates) < CARDS_PER_RUN * 3:
        query = QUERIES[pos % len(QUERIES)]
        pos += 1
        token, found = None, 0
        for _ in range(3):                   # до 3 страниц = до 60 мест на запрос
            if requests_done >= MAX_REQUESTS_PER_RUN:
                break
            try:
                places, token = search(query, token)
            except Exception as e:
                print(f"[sites] «{query}»: {e}")
                if requests_done == 0:
                    raise            # самый первый запрос упал — ключ/квота, а не сеть
                break
            requests_done += 1
            for p in places:
                pid = p.get("id")
                name = (p.get("displayName") or {}).get("text", "")
                if not pid or pid in state:
                    continue
                status = site_status(p.get("websiteUri"))
                reason = None
                if status == "site":
                    reason = "есть сайт"
                elif p.get("businessStatus", "OPERATIONAL") != "OPERATIONAL":
                    reason = "закрыта"
                elif not phone_digits(p):
                    reason = "нет телефона"
                elif (p.get("userRatingCount") or 0) < MIN_REVIEWS:
                    reason = "мало отзывов"
                elif any(w in name.lower() for w in SKIP_NAME_WORDS):
                    reason = "сеть или госорган"
                if reason:
                    # Помним только «окончательных» — остальных Google покажет снова.
                    if reason in ("есть сайт", "сеть или госорган"):
                        state[pid] = {"skip": reason, "date": datetime.now().date().isoformat()}
                    continue
                p["_query"] = query
                p["_status"] = status
                candidates.append(p)
                found += 1
            if not token:
                break
        print(f"[sites] «{query}»: без сайта {found}")
    unique = {}
    for p in candidates:
        unique.setdefault(p["id"], p)
    return list(unique.values()), pos, requests_done


PITCH_PROMPT = """Ты помогаешь девушке — веб-разработчику из Казахстана — продавать сайты
малому бизнесу холодными звонками. Ниже компании из Google Карт, у которых нет своего сайта.

Для КАЖДОЙ компании напиши:
1. "call" — скрипт первого звонка, 4–6 коротких реплик, разговорный русский, без
   канцелярита. Начни с приветствия и вопроса, можно ли поговорить с владельцем или
   управляющим. Сделай одно конкретное наблюдение о компании (рейтинг, число отзывов,
   ниша, город): например, что её хвалят в отзывах, но в поиске Google её сайта нет,
   и клиенты уходят к конкурентам с сайтом. Предложи бесплатно показать набросок
   главной страницы сайта именно для них. Закончи вопросом, удобно ли прислать
   набросок в WhatsApp.
2. "whatsapp" — сообщение в WhatsApp после звонка, 3–4 предложения: напомнить о
   разговоре, одна выгода сайта для их ниши, предложение показать набросок.

Правила: цены не называй, имя не придумывай, фактов о компании, которых нет в данных,
не выдумывай. Глаголы о себе — в женском роде.

Компании:
{items}

Ответ — строго JSON без пояснений:
{{"items": [{{"id": "id компании", "call": "скрипт", "whatsapp": "сообщение"}}]}}"""


def describe(p):
    reviews = p.get("userRatingCount") or 0
    lines = [
        f"id: {p['id']}",
        f"название: {(p.get('displayName') or {}).get('text', '')}",
        f"вид деятельности: {(p.get('primaryTypeDisplayName') or {}).get('text') or p['_query']}",
        f"адрес: {p.get('formattedAddress', '')}",
        f"рейтинг: {p.get('rating', '—')} ({reviews} отзывов)",
    ]
    if p["_status"] == "social":
        lines.append(f"вместо сайта в Google указано: {p.get('websiteUri')}")
    return "\n".join(lines)


def make_pitches(places):
    """Тексты для всех компаний одним запросом к ИИ (у бесплатного Gemini мало запросов в сутки)."""
    try:
        from example_generator import ask_ai
        answer = ask_ai(PITCH_PROMPT.format(items="\n\n".join(describe(p) for p in places)))
    except Exception as e:
        print(f"[sites] ИИ недоступен: {e}")
        answer = None
    result = {}
    for item in (answer or {}).get("items", []):
        if item.get("id") and item.get("call"):
            result[item["id"]] = item
    return result


def fallback_pitch(p):
    """Шаблон, если ИИ не ответил: звонить можно и по нему."""
    name = (p.get("displayName") or {}).get("text", "")
    reviews = p.get("userRatingCount") or 0
    call = (
        f"Здравствуйте! Подскажите, могу я поговорить с владельцем или управляющим «{name}»?\n"
        f"Я веб-разработчик, увидела вас в Google Картах: у вас {reviews} отзывов"
        f"{' и рейтинг ' + str(p['rating']) if p.get('rating') else ''}, а сайта нет — "
        "клиенты, которые ищут через Google, уходят к тем, у кого он есть.\n"
        "Могу бесплатно сделать набросок главной страницы именно для вас, чтобы вы посмотрели.\n"
        "Удобно, если пришлю его в WhatsApp?"
    )
    whatsapp = (
        f"Здравствуйте! Это по нашему разговору о сайте для «{name}». "
        "Сайт помогает клиентам найти вас в Google, посмотреть услуги и сразу записаться или позвонить. "
        "Сделаю набросок главной страницы бесплатно — пришлю сюда, как будет готов. Хорошо?"
    )
    return {"call": call, "whatsapp": whatsapp}


def card(p, n, total):
    name = (p.get("displayName") or {}).get("text", "")
    digits = phone_digits(p)
    kind = (p.get("primaryTypeDisplayName") or {}).get("text") or p["_query"]
    reviews = p.get("userRatingCount") or 0
    lines = [
        f"📞 {n}/{total} · {name}",
        f"{kind} · ⭐ {p.get('rating', '—')} ({reviews} отзывов)",
        f"📍 {p.get('formattedAddress', '')}",
        "",
        f"☎️ {pretty_phone(digits)}" + ("  (мобильный)" if is_mobile(digits) else ""),
    ]
    if is_mobile(digits):
        lines.append(f"WhatsApp: https://wa.me/{digits}")
    lines.append(f"Google Карты: {p.get('googleMapsUri', '')}")
    lines.append("")
    if p["_status"] == "social":
        lines.append(f"🌐 Сайта нет, вместо него — {p.get('websiteUri')}")
    else:
        lines.append("🌐 Сайта нет совсем")
    lines.append("Перед звонком загляни в 2ГИС/Instagram — вдруг сайт всё-таки есть.")
    return "\n".join(lines)


def run():
    if not API_KEY:
        alert_fail("site_hunter", "не задан GOOGLE_MAPS_API_KEY — без него поиск в Google Картах не работает")
        return
    state = load_state()
    start = int(state.pop(QUERY_POS_KEY, 0)) % len(QUERIES)
    try:
        candidates, pos, requests_done = collect(state, start)
    except Exception as e:
        state[QUERY_POS_KEY] = start
        save_state(state)
        alert_fail("site_hunter", f"Google Карты не ответили: {str(e)[:300]}")
        return

    candidates.sort(key=lambda p: -score(p, p["_status"]))
    chosen = candidates[:CARDS_PER_RUN]
    pitches = make_pitches(chosen) if chosen else {}

    if chosen:
        notify(f"☀️ Компании без сайта на сегодня: {len(chosen)}.\n"
               "На каждую — карточка, скрипт звонка и текст для WhatsApp после разговора.")
    for n, p in enumerate(chosen, 1):
        texts = pitches.get(p["id"]) or fallback_pitch(p)
        notify(card(p, n, len(chosen)))
        notify("🗣 Скрипт звонка:\n\n" + texts["call"])
        if texts.get("whatsapp"):
            notify(texts["whatsapp"])   # отдельным сообщением — чтобы скопировать целиком
        state[p["id"]] = {
            "sent": datetime.now().date().isoformat(),
            "name": (p.get("displayName") or {}).get("text", ""),
            "phone": phone_digits(p), "query": p["_query"],
        }

    state[QUERY_POS_KEY] = pos % len(QUERIES)
    save_state(state)
    print(f"[sites] Запросов: {requests_done}, без сайта: {len(candidates)}, карточек: {len(chosen)}, "
          f"ИИ-текстов: {len(pitches)}")
    if not chosen:
        notify("🔎 Сегодня новых компаний без сайта не нашлось — завтра поищу в других городах и нишах.")


if __name__ == "__main__":
    run()
