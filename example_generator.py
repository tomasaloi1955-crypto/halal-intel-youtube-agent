# example_generator.py — «крючок» для продажи автопостинга. По ссылке на открытый
# Telegram-канал читает последние посты, пишет 3 новых поста в стиле этого канала и
# готовое первое сообщение владельцу. Результат сохраняется в output/examples/ и
# приходит в Telegram — остаётся переслать владельцу канала.
#
#   python example_generator.py t.me/имя_канала
#   или двойной клик по make_example.cmd — он сам спросит ссылку.
import html
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

import google.generativeai as genai

from ai_processor import CHANNEL_LINK, _call_groq_fallback, _parse_json
from telegram_notify import notify

OUT_DIR = os.path.join("output", "examples")
# Своя модель, а не gemini-2.5-flash из ai_processor: квота бесплатного Gemini считается
# отдельно на каждую модель (20 запросов/сутки), и генератор не должен съедать квоту
# YouTube-автопилота (19.09.2026 после тестов генератора 2.5-flash упёрся в лимит).
EXAMPLES_MODEL = os.getenv("EXAMPLES_GEMINI_MODEL", "gemini-3.6-flash")
MAX_POSTS_FOR_STYLE = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def channel_name(link):
    """t.me/name, https://t.me/s/name/123, @name → name."""
    link = link.strip()
    m = re.search(r"(?:t\.me/(?:s/)?|@)([A-Za-z0-9_]{4,})", link)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_]{4,}", link):
        return link
    raise ValueError(f"Не похоже на ссылку на Telegram-канал: {link!r}")


def _meta(page, prop):
    m = re.search(rf'<meta property="{prop}" content="([^"]*)"', page)
    return html.unescape(m.group(1)) if m else ""


def fetch_channel(name):
    """Открытая веб-версия канала t.me/s/… — без входа в аккаунт, последние ~20 постов."""
    resp = requests.get(f"https://t.me/s/{name}", headers=HEADERS, timeout=20)
    resp.raise_for_status()
    page = resp.text
    if "tgme_channel_info" not in page:
        raise ValueError(
            f"Канал @{name} не найден или закрыт — генератор работает только с открытыми каналами"
        )
    posts = []
    for raw in re.findall(
        r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', page, re.S
    ):
        text = re.sub(r"<br\s*/?>", "\n", raw)
        text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
        if len(text) > 40:
            posts.append(text)
    dates = [
        datetime.fromisoformat(d)
        for d in re.findall(r'<time datetime="([^"]+)"', page)
    ]
    return {
        "name": name,
        "title": _meta(page, "og:title"),
        "description": _meta(page, "og:description"),
        "posts": posts[-MAX_POSTS_FOR_STYLE:],
        "dates": dates,
    }


def activity(dates):
    """Как давно был последний пост и как часто канал выходит — аргумент для владельца."""
    if not dates:
        return None, None
    now = datetime.now(timezone.utc)
    days_silent = (now - max(dates)).days
    span_days = max((max(dates) - min(dates)).days, 1)
    per_week = round(len(dates) / span_days * 7, 1)
    return days_silent, per_week


PROMPT = """Ты помогаешь фрилансеру продать услугу «автопостинг в Telegram»: посты выходят
каждый день сами, владелец только утверждает темы. Чтобы зацепить владельца канала,
нужно показать, как его канал мог бы выглядеть, а не рассказывать про технологии.

Канал: «{title}» (@{name})
Описание канала: {description}
Активность: {activity}

Последние посты канала (от старых к новым):
{posts}

Задача:
1. Коротко определи стиль канала: тема, тон, длина постов, эмодзи, структура, призыв в конце.
2. Напиши 3 НОВЫХ поста для этого канала, неотличимых по стилю от его постов (та же длина,
   та же подача, те же приёмы оформления). Темы — свежие, не повторяющие последние посты,
   полезные его аудитории. Если канал продаёт товар/услугу — хотя бы один пост продающий.
   Не выдумывай конкретные цены, адреса, акции, отзывы и факты о бизнесе, которых нет в постах.
3. Напиши первое сообщение владельцу канала от лица девушки-фрилансера. Коротко (4–6
   предложений), по-человечески, без канцелярита и без слов «ИИ», «нейросеть», «автоматизация»
   в первой фразе. Начни с «Ас-саляму алейкум!», если канал мусульманский, иначе с «Здравствуйте!».
   Сделай конкретное наблюдение о его канале (если давно не было постов — мягко упомяни это),
   скажи, что сделала 3 примера постов в его стиле, и предложи прислать. Контакт не добавляй,
   имя не называй и не придумывай.

Аяты и хадисы — СТРОГО. Текст аятов и хадисов САМА НЕ ПИШИ никогда, даже пересказом в
кавычках: вместо него ставь метку, программа вставит дословный текст из источника.
- Аят: метка [[АЯТ сура:аят | слово]], например [[АЯТ 2:153 | терпени]]. «слово» — основа
  слова, которое точно есть в этом аяте в русском переводе (Абу Аделя или Кулиева). Перед меткой можно
  написать «Всевышний Аллах говорит:», после — ничего не добавляй (номер вставится сам).
- Хадис: метка [[ХАДИС | слово1, слово2, слово3]], например [[ХАДИС | дела, оценива,
  намерени]]. 3–4 основы слов, стоящих РЯДОМ в одной фразе хадиса в русском переводе.
  Ищется ТОЛЬКО в «Сахих аль-Бухари» и «Сахих Муслим»; хадисы из других сборников, слабые и сомнительные — запрещены.
  Хадис вставится целиком, начиная с «Сообщается от…», с источником — поэтому перед меткой
  не пиши «Пророк сказал», а после — ничего.
- Высказывания учёных и «мудрые цитаты» не приписывай никому.
Не уверена в аяте или хадисе — обходись без цитаты: пост без цитат лучше недостоверного.

Жёсткие правила: никакого харама (алкоголь, азарт, риба, свинина, откровенный контент),
никаких изображений людей не предлагать. Пиши на языке канала.

Ответ — строго JSON без пояснений:
{{"style": "2–3 предложения о стиле",
  "posts": ["пост 1", "пост 2", "пост 3"],
  "pitch": "сообщение владельцу"}}"""


def ask_ai(prompt):
    """Gemini (своя модель), при сбое — Groq, если его ключ задан. Возвращает dict или None."""
    try:
        text = genai.GenerativeModel(EXAMPLES_MODEL).generate_content(prompt).text
    except Exception as e:
        print(f"[examples] Gemini {EXAMPLES_MODEL} недоступен ({str(e)[:160]}), пробую Groq...")
        try:
            text = _call_groq_fallback(prompt)
        except Exception as e2:
            print(f"[examples] Groq тоже недоступен: {e2}")
            return None
    try:
        return _parse_json(text)
    except Exception as e:
        print(f"[examples] Ответ ИИ не разобран: {e}")
        return None


def generate(channel):
    days_silent, per_week = activity(channel["dates"])
    if days_silent is None:
        activity_text = "неизвестно"
    else:
        activity_text = (
            f"последний пост {days_silent} дн. назад, в среднем {per_week} постов в неделю"
        )
    posts = "\n\n---\n\n".join(p[:1500] for p in channel["posts"])
    prompt = PROMPT.format(
        title=channel["title"], name=channel["name"],
        description=channel["description"] or "нет", activity=activity_text, posts=posts,
    )
    # Посты с недостоверными цитатами выбрасываем и досоздаём заново (до 3 попыток —
    # у Gemini всего 20 запросов в сутки).
    result, good = None, []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        answer = ask_ai(prompt)
        if not answer or not answer.get("posts") or not answer.get("pitch"):
            continue
        result = result or answer
        for post in answer["posts"]:
            try:
                post = insert_quotes(post)
            except BadQuote as e:
                print(f"[examples] Попытка {attempt}: пост отброшен — {e}")
                continue
            if len(good) < 3:
                good.append(post)
        if len(good) == 3:
            break
    if not result:
        raise RuntimeError("ИИ не вернул примеры — попробуй ещё раз позже (возможно, кончилась дневная квота)")
    if len(good) < 3:
        raise RuntimeError(
            f"ИИ за {MAX_ATTEMPTS} попытки не написал 3 поста без недостоверных цитат — "
            "попробуй ещё раз позже"
        )
    result["posts"] = good
    result["activity"] = activity_text
    return result


MAX_ATTEMPTS = 3

# ── Аяты и хадисы ─────────────────────────────────────────────────────────────
# Правило владелицы (19.09.2026): аяты — только дословно, хадисы — только из «Сахих
# аль-Бухари» и «Сахих Муслим», недостоверное нельзя. ИИ дословность не гарантирует
# (в тесте написал «к терпению и молитве» вместо «намазу» у Кулиева), поэтому текст
# цитат ИИ не пишет вовсе: ставит метку, а программа вставляет текст из источника.
#   • аяты — перевод Абу Аделя с quran.com (translation id 79) — выбор владелицы;
#   • хадисы — русские «Сахих аль-Бухари» и «Сахих Муслим» (fawazahmed0/hadith-api),
#     поиск по словам из метки. Не нашлось — пост отбрасывается.
QURAN_API = "https://api.quran.com/api/v4/quran/translations/{}"
AYAH_TRANSLATION = 79     # Абу Адель — этот текст вставляется в пост
CHECK_TRANSLATION = 45    # Кулиев — только для сверки номера аята по слову из метки
HADITH_EDITIONS = [("аль-Бухари", "rus-bukhari"), ("Муслим", "rus-muslim")]
HADITH_URL = "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/{}.min.json"
HADITH_CACHE_DIR = os.path.join("output", "cache")
MAX_HADITH_CHARS = 900
MIN_HADITH_STEMS = 3      # по 1–2 словам находятся хадисы не по теме
MAX_STEMS_WINDOW = 120    # слова метки должны стоять в одной фразе хадиса

AYAH_MARK_RE = re.compile(r"\[\[\s*АЯТ\s+(\d{1,3})\s*:\s*(\d{1,3})\s*\|\s*([^\]]+?)\s*\]\]", re.I)
HADITH_MARK_RE = re.compile(r"\[\[\s*ХАДИС\s*\|\s*([^\]]+?)\s*\]\]", re.I)

# Цитата, написанная ИИ самостоятельно (без метки), — признак недостоверности.
QUOTE_SIGNAL_RE = re.compile(
    r"хадис|пророк|посланник|передаётся|передается|передал|сообщается от|сура|аят|коран"
    r"|(аллах|всевышний)[^.!?\n]{0,30}(говорит|сказал)|бухари|муслим\b|тирмиз|абу\s+да[ув]у?д"
    r"|насаи|ибн\s+мадж|муснад|байхак|табаран",
    re.I,
)
# «Пророк сказал: …» без кавычек — после двоеточия должна идти метка, а не текст ИИ.
UNQUOTED_SAYING_RE = re.compile(
    r"(пророк|посланник|аллах|всевышн|коран)[^.!?\n]{0,80}(говорит|говорил|сказал|сказано)"
    r"\s*:\s*(?!⟦Q⟧)\S",
    re.I,
)
QUOTED_RE = re.compile(r"«[^»]{20,}»|\"[^\"]{20,}\"|“[^”]{20,}”")


class BadQuote(Exception):
    pass


_ayah_cache = {}
_hadith_books = {}


def fetch_ayah(sura, ayah, translation=AYAH_TRANSLATION):
    key = (f"{int(sura)}:{int(ayah)}", translation)
    if key not in _ayah_cache:
        resp = requests.get(QURAN_API.format(translation), params={"verse_key": key[0]}, timeout=20)
        resp.raise_for_status()
        items = resp.json().get("translations") or []
        text = re.sub(r"<[^>]+>", "", items[0]["text"]).strip() if items else ""
        _ayah_cache[key] = text
    return _ayah_cache[key]


def hadith_book(edition):
    """Русский сборник целиком (~8 МБ), скачивается один раз и лежит в output/cache."""
    if edition not in _hadith_books:
        path = os.path.join(HADITH_CACHE_DIR, f"{edition}.json")
        if not os.path.exists(path):
            os.makedirs(HADITH_CACHE_DIR, exist_ok=True)
            resp = requests.get(HADITH_URL.format(edition), timeout=120)
            resp.raise_for_status()
            with open(path, "wb") as f:
                f.write(resp.content)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _hadith_books[edition] = [
            (h["hadithnumber"], h["text"].strip()) for h in data["hadiths"] if h["text"].strip()
        ]
    return _hadith_books[edition]


def _stems_window(low, stems):
    """Длина самого короткого куска текста, где встречаются все слова метки.
    Слова рядом — значит, это одна мысль хадиса, а не случайные совпадения."""
    hits = sorted(
        (m.start(), i) for i, s in enumerate(stems) for m in re.finditer(re.escape(s), low)
    )
    best, last = None, {}
    for pos, i in hits:
        last[i] = pos
        if len(last) == len(stems):
            span = pos - min(last.values())
            best = span if best is None else min(best, span)
    return best


def find_hadith(words):
    """Хадис из аль-Бухари/Муслима, где все слова метки стоят ближе всего друг к другу."""
    stems = [w.strip().lower() for w in words.split(",") if w.strip()]
    if len(stems) < MIN_HADITH_STEMS:
        return None
    best = None
    for source, edition in HADITH_EDITIONS:
        for number, text in hadith_book(edition):
            if len(text) > MAX_HADITH_CHARS:
                continue
            low = text.lower()
            if not all(s in low for s in stems):
                continue
            window = _stems_window(low, stems)
            if window is None or window > MAX_STEMS_WINDOW:
                continue
            rank = (window, len(text))
            if best is None or rank < best[0]:
                best = (rank, source, number, text)
    return best[1:] if best else None


def insert_quotes(post):
    """Меняет метки на дословный текст. Цитата без метки или ненайденная — BadQuote."""
    residual = HADITH_MARK_RE.sub("⟦Q⟧", AYAH_MARK_RE.sub("⟦Q⟧", post))
    if UNQUOTED_SAYING_RE.search(residual):
        raise BadQuote("слова Аллаха или Пророка ﷺ написаны ИИ без метки")
    for m in QUOTED_RE.finditer(residual):
        context = residual[max(0, m.start() - 150):m.end() + 60]
        if QUOTE_SIGNAL_RE.search(context):
            raise BadQuote(f"цитата написана ИИ без проверки источника: {m.group(0)[:60]}…")
    if re.search(r"тирмиз|абу\s+да[ув]у?д|насаи|ибн\s+мадж|муснад|байхак|табаран", residual, re.I):
        raise BadQuote("упомянут сборник хадисов, кроме аль-Бухари и Муслима")

    def ayah_sub(m):
        sura, ayah, stem = m.group(1), m.group(2), m.group(3).strip().lower()
        text = fetch_ayah(sura, ayah)
        if not text:
            raise BadQuote(f"аята {sura}:{ayah} не существует")
        # Номер сверяем по слову из метки в обоих переводах (формулировки Кулиева ИИ
        # знает лучше), а вставляем всегда перевод Абу Аделя.
        if stem not in text.lower() and stem not in fetch_ayah(sura, ayah, CHECK_TRANSLATION).lower():
            raise BadQuote(f"в аяте {sura}:{ayah} нет слова «{stem}» — ИИ перепутал номер")
        # Аят-продолжение (94:6 «поистине, с тягостью…») начинается со строчной.
        return f"«{text[0].upper()}{text[1:]}» (Сура {int(sura)}, аят {int(ayah)})"

    def hadith_sub(m):
        found = find_hadith(m.group(1))
        if not found:
            raise BadQuote(f"в аль-Бухари и Муслиме нет хадиса со словами: {m.group(1)}")
        source, number, text = found
        return f"{text} ({source}, № {number})"

    post = AYAH_MARK_RE.sub(ayah_sub, post)
    post = HADITH_MARK_RE.sub(hadith_sub, post)
    if "[[" in post:
        raise BadQuote("метка цитаты в неверном формате")
    return post


def quote_warning(result):
    if any(re.search(r"\(Сура \d+, аят \d+\)|\((аль-Бухари|Муслим), № ", p) for p in result["posts"]):
        return ("ℹ️ Аяты и хадисы вставлены программой дословно: аяты — перевод Абу Аделя "
                "(quran.com), хадисы — только «Сахих аль-Бухари» и «Сахих Муслим». "
                "Проверь только, что цитата по смыслу подходит к посту.")
    return ""


def render(channel, result):
    lines = [
        f"# Примеры для @{channel['name']} — {channel['title']}",
        f"https://t.me/{channel['name']}",
        f"Активность: {result['activity']}",
        f"Стиль: {result['style']}",
        quote_warning(result),
        "",
        "## Сообщение владельцу",
        result["pitch"],
        "",
    ]
    for i, post in enumerate(result["posts"], 1):
        lines += [f"## Пример {i}", post, ""]
    lines += [
        "---",
        f"Когда владелец ответит «присылайте» — отправь примеры и ссылку на свой канал "
        f"как доказательство, что автопостинг работает: {CHANNEL_LINK}",
    ]
    return "\n".join(lines)


def send_to_telegram(channel, result):
    """Отдельными сообщениями — чтобы каждое можно было переслать владельцу как есть."""
    notify(f"🎯 Примеры для @{channel['name']} ({channel['title']})\n"
           f"Активность: {result['activity']}\n\nНиже: сообщение владельцу и 3 примера.\n"
           + quote_warning(result))
    notify(result["pitch"])
    for post in result["posts"]:
        notify(post)


def main(link):
    channel = fetch_channel(channel_name(link))
    if len(channel["posts"]) < 3:
        raise ValueError(f"В канале @{channel['name']} меньше 3 текстовых постов — стиль не понять")
    result = generate(channel)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{channel['name']}.md")
    text = render(channel, result)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    send_to_telegram(channel, result)
    print(text)
    print(f"\nСохранено: {path} (и отправлено тебе в Telegram)")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else input("Ссылка на Telegram-канал: ")
    try:
        main(arg)
    except Exception as e:
        print(f"Не получилось: {e}")
        sys.exit(1)
