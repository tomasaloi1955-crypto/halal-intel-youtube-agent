# channel_hunter.py — ищет владельцев Telegram-каналов, которым можно продать
# автопостинг, и готовит для каждого персональное сообщение в личку.
#
# ВАЖНО: агент НЕ пишет людям сам. Ботам Telegram запрещено писать первыми, а
# автоматическая рассылка с личного аккаунта — спам, за который блокируют номер.
# Поэтому агент делает всё, кроме последнего шага: находит канал, считает, как
# давно он молчит, достаёт контакт владельца, пишет текст — и присылает карточку
# владелице. Ей остаётся открыть личку по ссылке, вставить текст и отправить.
#
# Источники кандидатов:
#   • поиск каналов на lyzem.com по нишевым запросам;
#   • «снежный ком» — упоминания @каналов в описаниях и постах уже найденных.
# Проверка — по открытым страницам t.me (без входа в аккаунт и без API).
import html
import json
import os
import random
import re
import time
from datetime import datetime, timezone

import requests

from paths import dpath
from telegram_notify import notify, alert_fail

SEEN_FILE = dpath("seen_channels.json")
QUEUE_KEY = "_queue"          # очередь непроверенных каналов хранится там же
QUERY_POS_KEY = "_query_pos"  # с какого поискового запроса начать следующий запуск
CARDS_PER_RUN = int(os.getenv("HUNTER_CARDS", "5"))
MAX_CHECKS_PER_RUN = int(os.getenv("HUNTER_CHECKS", "60"))
MAX_QUEUE = 500
MIN_SUBSCRIBERS = 200
MAX_SUBSCRIBERS = 200_000
MIN_SILENT_DAYS = 2          # вчера постивший канал в услуге не нуждается
MAX_SILENT_DAYS = 400        # совсем мёртвые каналы владельцу уже не интересны
REQUEST_DELAY = (2.0, 4.0)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# Ниши, в которых ищем клиентов. Первые — мусульманские (там владелица «своя»),
# дальше — соседние женские и локальные темы.
SEARCH_QUERIES = [
    "мусульманка", "хиджаб", "халяль", "исламский магазин", "мусульманские товары",
    "скромная одежда", "абая", "никаб", "мусульманская мода", "исламская школа",
    "арабский язык", "коран онлайн", "мусульманский психолог", "халяль еда",
    "мусульманская семья", "женский клуб", "рукоделие", "домашняя выпечка",
    "платки хиджабы", "мусульманская одежда", "химар", "джильбаб", "закрытые платья",
    "исламские книги", "таджвид", "хифз", "уроки корана", "намаз для начинающих",
    "мусульманские имена", "исламские подарки", "сурьма", "мисвак", "благовония масла",
    "халяль косметика", "халяль кафе", "халяль мясо", "умра туры", "хадж туры",
    "мусульманская свадьба", "никах", "сестры в исламе", "мусульманский блог",
    "исламское воспитание детей", "мусульманский детский сад", "хиджама",
    "травы сунна", "мед сунна", "черный тмин", "исламская психология",
    "арабский для детей", "мусульманка москва", "мусульманка казань",
    "мусульманка дагестан", "мусульманка чечня", "мусульманка алматы",
    "мусульманка ташкент", "халяль москва", "халяль казань", "хиджаб махачкала",
]
QUERIES_PER_RUN = 8
SEARCH_PAGES = 2              # поиск по постам: каналы с 1-й и 2-й страницы выдачи
RECHECK_DAYS = 30             # «молчит», «нет контакта» — через месяц смотрим снова
RECHECK_REASONS = ("молчит", "нет контакта", "подписчиков", "нет постов")

NICHE_KEYWORDS = [
    "ислам", "мусульман", "халяль", "халал", "хиджаб", "никаб", "абая", "мечет",
    "намаз", "коран", "сунна", "умра", "хадж", "шариат", "мусульманка", "сестёр",
    "арабск", "скромная одежда", "модест",
]
# Соседние ниши — тоже клиенты, но без мусульманского приветствия.
GENERAL_KEYWORDS = [
    "магазин", "доставка", "курс", "обучение", "школа", "мастер", "салон", "студия",
    "психолог", "тренер", "рукодел", "выпечк", "handmade", "запись", "услуг",
]

# Каналы, которые нам не нужны: чужие рекламные помойки и явный харам.
# Проверяется по НАЗВАНИЮ и ОПИСАНИЮ канала — то есть по теме канала. В постах такие
# слова мелькают безобидно («халяльна ли криптовалюта»), и по ним отбрасывать нельзя.
SKIP_KEYWORDS = [
    "казино", "ставки", "букмекер", "беттинг", "форекс", "трейдинг", "криптовалют",
    "заработок в интернете", "инвестиц", "займ", "кредит", "алкогол", "18+", "эротик",
    "порно", "знакомств", "накрутк", "биржа рекламы", "куплю канал", "продажа каналов",
]
# А это — и в постах тоже: такой канал нам не клиент, чем бы он себя ни называл.
HARD_SKIP_KEYWORDS = [
    "казино", "букмекер", "ставки на спорт", "форекс", "порно", "эротик", "интим-",
]

OWN_CHANNELS = {"halalaifreya", "ilikeislamandsport", "i_speak_en", "myarabicl", "halal_intelligence"}


def polite_get(url, timeout=25):
    time.sleep(random.uniform(*REQUEST_DELAY))
    return requests.get(url, headers=HEADERS, timeout=timeout)


def strip_tags(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def parse_subscribers(text):
    """«1 234 subscribers», «12.5K subscribers» → число."""
    m = re.search(r"([\d\s.,]+)\s*([KMkm]?)\s*(?:subscribers|подписчик)", text or "")
    if not m:
        return None
    raw = m.group(1).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(value * {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1))


CONTACT_RE = re.compile(r"@([A-Za-z0-9_]{5,32})")
CONTACT_HINT_RE = re.compile(
    r"(админ|adm|владел|связ|вопрос|сотруднич|реклам|заказ|писать|contact|owner|pr\b|менеджер)",
    re.I,
)


HANDLE_RE = re.compile(r"(?:@|t\.me/|telegram\.me/)([A-Za-z0-9_]{5,32})")
_person_cache = {}


def is_person(handle):
    """Живой человек, которому можно написать в личку, — а не канал, группа или бот.
    Страница t.me/<ник> у человека: кнопка «Send Message» и «@ник» вместо счётчика
    подписчиков; у каналов и групп — «N subscribers/members», у ботов — «Start Bot»."""
    key = handle.lower()
    if key not in _person_cache:
        try:
            page = polite_get(f"https://t.me/{handle}").text
        except Exception:
            return False   # не смогли проверить — не рискуем, ссылку не даём
        extra = re.search(r'tgme_page_extra">\s*([^<]*)', page)
        button = re.search(r'tgme_action_button_new[^>]*>([^<]*)', page)
        _person_cache[key] = bool(
            extra and extra.group(1).strip().startswith("@")
            and button and button.group(1).strip() == "Send Message"
        )
    return _person_cache[key]


def find_contact(name, description, posts):
    """Личка владельца: @ник или t.me/ник в описании канала либо рядом со словами
    «админ», «по вопросам», «реклама» в постах. Каждый ник проверяется на t.me —
    в карточку попадает только настоящий человек."""
    tried = set()
    for text in [description] + list(reversed(posts)):
        for m in HANDLE_RE.finditer(text or ""):
            handle = m.group(1)
            low = handle.lower()
            if low in tried or low in (name.lower(), "telegram", "joinchat", "share") \
                    or low.endswith("bot"):
                continue
            around = (text[max(0, m.start() - 80):m.end() + 40]).lower()
            if not (CONTACT_HINT_RE.search(around) or text is description):
                continue
            tried.add(low)
            if is_person(handle):
                return handle
            if len(tried) >= 4:
                return None
    return None


def fetch_channel(name):
    """Данные открытого канала или None, если это не канал (или он закрыт)."""
    resp = polite_get(f"https://t.me/s/{name}")
    resp.raise_for_status()
    page = resp.text
    if "tgme_channel_info" not in page:
        return None
    title = re.search(r'og:title" content="([^"]*)"', page)
    title = html.unescape(title.group(1)) if title else name
    if title.startswith("Telegram: Contact"):
        return None
    desc = re.search(r'og:description" content="([^"]*)"', page)
    desc = html.unescape(desc.group(1)) if desc else ""
    counter = re.search(
        r'counter_value">([^<]+)</span>\s*<span class="counter_type">(?:subscribers|подписчик)', page)
    subs = parse_subscribers(f"{counter.group(1)} subscribers") if counter else None
    posts = [strip_tags(p) for p in re.findall(
        r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', page, re.S)]
    dates = [datetime.fromisoformat(d) for d in re.findall(r'<time datetime="([^"]+)"', page)]
    # «Снежный ком»: @упоминания в тексте + все ссылки на каналы со страницы
    # (репосты «Forwarded from», ссылки в постах) — главный источник новых кандидатов.
    mentions = {m.lower() for text in [desc] + posts for m in CONTACT_RE.findall(text)}
    mentions |= {m.lower() for m in re.findall(r'https://t\.me/([A-Za-z0-9_]{5,32})(?:["/?]|\b)', page)}
    mentions -= {name.lower(), "share", "iv", "joinchat", "telegram", "s"}
    return {
        "name": name, "title": title, "description": desc, "subscribers": subs,
        "posts": [p for p in posts if len(p) > 40], "dates": dates, "mentions": mentions,
    }


def activity(dates):
    """(дней молчания, постов в неделю) по последним постам страницы."""
    if not dates:
        return None, 0.0
    now = datetime.now(timezone.utc)
    silent = (now - max(dates)).days
    span = max((max(dates) - min(dates)).days, 1)
    return silent, round(len(dates) / span * 7, 1)


def search_lyzem(query):
    """Каналы из поиска lyzem.com — без ключей и регистрации. Поиск по каналам
    отдаёт всегда одни и те же ~5 штук, поэтому добавляем поиск по постам: там
    каналы-авторы найденных постов, и выдача листается."""
    q = requests.utils.quote(query)
    urls = [f"https://lyzem.com/search?q={q}&type=channel"]
    urls += [f"https://lyzem.com/search?q={q}&f=all&p={p}&per-page=10"
             for p in range(1, SEARCH_PAGES + 1)]
    names = []
    for url in urls:
        resp = polite_get(url)
        resp.raise_for_status()
        names += re.findall(r'href="https://t\.me/([A-Za-z0-9_]{4,})', resp.text)
    return [n for n in dict.fromkeys(names)
            if not n.lower().endswith("bot") and "lyzem" not in n.lower()]


def recheck_due(entry):
    """Пропущенный канал пора проверить снова: молчал, не было контакта и т. п."""
    skip = entry.get("skip", "")
    if not skip.startswith(RECHECK_REASONS):
        return False
    days = re.match(r"молчит (\d+)", skip)
    if days and int(days.group(1)) > MAX_SILENT_DAYS:
        return False   # заброшен больше года — уже не оживёт
    try:
        age = (datetime.now().date() - datetime.fromisoformat(entry["date"]).date()).days
    except Exception:
        return True
    return age >= RECHECK_DAYS


def score(info, silent, per_week, niche):
    """Чем выше, тем нужнее владельцу наша услуга."""
    points = 0
    if silent >= 30:
        points += 40           # канал заброшен — главный повод написать
    elif silent >= 10:
        points += 30
    elif silent >= 4:
        points += 20
    if per_week < 1.5:
        points += 20           # ведётся нерегулярно
    elif per_week < 4:
        points += 10
    if niche == "muslim":
        points += 25           # владелица «своя», отклик выше
    subs = info["subscribers"] or 0
    if 1_000 <= subs <= 50_000:
        points += 15           # есть аудитория и, значит, деньги
    elif subs >= 300:
        points += 5
    return points


def classify(info):
    """'muslim' | 'general' | None — подходит ли канал под услугу."""
    about = f"{info['title']} {info['description']}".lower()
    text = f"{about} {' '.join(info['posts'][:8])}".lower()
    if any(k in about for k in SKIP_KEYWORDS) or any(k in text for k in HARD_SKIP_KEYWORDS):
        return None
    if any(k in text for k in NICHE_KEYWORDS):
        return "muslim"
    if any(k in text for k in GENERAL_KEYWORDS):
        return "general"
    return None


PITCH_PROMPT = """Ты пишешь первое сообщение в личку владельцу Telegram-канала от лица
девушки-фрилансера, которая настраивает автопостинг: посты выходят каждый день сами,
владелец только утверждает темы.

Канал: «{title}» (@{name}), подписчиков: {subs}
Описание канала: {description}
Активность: {activity}
Последние посты канала:
{posts}

Напиши сообщение: 4–6 предложений, по-человечески, без канцелярита.
- Начни с «{greeting}»
- Сделай КОНКРЕТНОЕ наблюдение об этом канале (о чём он, что понравилось). Если давно
  не было постов — мягко упомяни это, без упрёка.
- Предложи прислать 3 примера постов в его стиле бесплатно, чтобы он посмотрел.
- Закончи вопросом.
- Не называй цены, не пиши слова «ИИ», «нейросеть», «автоматизация» в первой фразе,
  не придумывай себе имя, не приписывай каналу фактов, которых нет.
- Не цитируй аяты и хадисы.
Выведи ТОЛЬКО текст сообщения."""


def make_pitch(info, silent, per_week, niche):
    from example_generator import ask_ai  # тот же Gemini, что и в генераторе примеров
    activity_text = f"последний пост {silent} дн. назад, в среднем {per_week} постов в неделю"
    prompt = PITCH_PROMPT.format(
        title=info["title"], name=info["name"], subs=info["subscribers"] or "неизвестно",
        description=info["description"] or "нет", activity=activity_text,
        posts="\n---\n".join(p[:400] for p in info["posts"][-3:]) or "нет",
        greeting="Ас-саляму алейкум!" if niche == "muslim" else "Здравствуйте!",
    )
    answer = ask_ai(f"{prompt}\n\nОтвет — строго JSON: {{\"message\": \"текст\"}}")
    return (answer or {}).get("message", "").strip()


def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=1)


def card(info, silent, per_week, niche, contact):
    subs = f"{info['subscribers']:,}".replace(",", " ") if info["subscribers"] else "?"
    lines = [
        f"{'🕌' if niche == 'muslim' else '📣'} {info['title']} — @{info['name']}",
        f"https://t.me/{info['name']}",
        f"Подписчиков: {subs} · последний пост {silent} дн. назад · {per_week} постов/нед.",
    ]
    lines.append(f"✍️ Написать владельцу: https://t.me/{contact}")
    lines.append("👇 Готовое сообщение — следующим сообщением, проверь и отправь")
    return "\n".join(lines)


def run():
    state = load_seen()
    # Очередь непроверенных каналов переживает запуск: «снежный ком» приносит их
    # быстрее, чем мы успеваем проверять (каждая проверка — пауза в пару секунд).
    queue = list(state.pop(QUEUE_KEY, []))
    # Запросы идут по кругу, а не случайно — за неделю перебираются все.
    start = int(state.pop(QUERY_POS_KEY, 0)) % len(SEARCH_QUERIES)
    seen = state
    # Каналы, отложенные месяц назад («молчит», «нет контакта»), — снова в работу.
    recheck = [name for name, entry in seen.items() if recheck_due(entry)]
    for name in recheck:
        del seen[name]
    todays = [SEARCH_QUERIES[(start + i) % len(SEARCH_QUERIES)] for i in range(QUERIES_PER_RUN)]
    for query in todays:
        try:
            found = search_lyzem(query)
        except Exception as e:
            print(f"[hunter] Поиск «{query}» не удался: {e}")
            continue
        print(f"[hunter] «{query}»: найдено {len(found)}")
        queue.extend(found)
    queue += recheck   # свежие находки — первыми, перепроверка — после них

    candidates = []
    checked = 0
    pending = list(dict.fromkeys(queue))
    queue = []
    while pending:
        name = pending.pop(0)
        low = name.lower()
        if low in seen or low in OWN_CHANNELS:
            continue
        if checked >= MAX_CHECKS_PER_RUN:
            queue.append(low)     # доедет до следующего запуска
            continue
        try:
            info = fetch_channel(name)
        except Exception as e:
            print(f"[hunter] @{name}: {e}")
            continue
        checked += 1
        if not info:
            seen[low] = {"skip": "не канал или закрыт", "date": datetime.now().date().isoformat()}
            continue
        silent, per_week = activity(info["dates"])
        niche = classify(info)
        # Снежный ком — только от каналов по теме: соседи случайного канала про
        # машины или новости тоже не наши (так 2/3 проверок уходили впустую).
        if niche:
            for mention in info["mentions"]:
                if mention not in seen and mention not in OWN_CHANNELS:
                    pending.append(mention)
        subs = info["subscribers"] or 0
        reason = None
        if not niche:
            reason = "не наша ниша"
        elif silent is None:
            reason = "нет постов"
        elif not (MIN_SILENT_DAYS <= silent <= MAX_SILENT_DAYS):
            reason = f"молчит {silent} дн."
        elif not (MIN_SUBSCRIBERS <= subs <= MAX_SUBSCRIBERS):
            reason = f"подписчиков {subs}"
        if reason:
            seen[low] = {"skip": reason, "date": datetime.now().date().isoformat()}
            continue
        candidates.append((score(info, silent, per_week, niche), info, silent, per_week, niche))

    candidates.sort(key=lambda c: -c[0])
    sent = no_contact = 0
    for points, info, silent, per_week, niche in candidates:
        if sent >= CARDS_PER_RUN:
            break
        contact = find_contact(info["name"], info["description"], info["posts"])
        if not contact:
            # Без лички владельца карточка бесполезна — не присылаем, вернёмся через месяц.
            seen[info["name"].lower()] = {"skip": "нет контакта владельца",
                                          "date": datetime.now().date().isoformat()}
            no_contact += 1
            continue
        try:
            pitch = make_pitch(info, silent, per_week, niche)
        except Exception as e:
            print(f"[hunter] @{info['name']}: сообщение не написано — {e}")
            continue
        if not pitch:
            continue
        # Два отдельных сообщения: карточка канала и чистый текст письма —
        # второе можно скопировать целиком и сразу переслать владельцу.
        notify(card(info, silent, per_week, niche, contact))
        notify(pitch)
        seen[info["name"].lower()] = {
            "sent": datetime.now().date().isoformat(), "title": info["title"],
            "contact": contact, "score": points, "silent": silent,
        }
        sent += 1

    # Непроверенные кандидаты — в очередь на следующий запуск (самые свежие сверху).
    seen[QUEUE_KEY] = list(dict.fromkeys(queue))[:MAX_QUEUE]
    seen[QUERY_POS_KEY] = (start + QUERIES_PER_RUN) % len(SEARCH_QUERIES)
    save_seen(seen)
    print(f"[hunter] Проверено каналов: {checked}, кандидатов: {len(candidates)}, "
          f"без контакта: {no_contact}, карточек: {sent}, в очереди: {len(seen[QUEUE_KEY])}")
    if checked and not candidates:
        print("[hunter] Подходящих каналов в этот раз нет")
    if not checked:
        alert_fail("channel_hunter", "ни один канал не проверен — похоже, источник поиска недоступен")


if __name__ == "__main__":
    run()
