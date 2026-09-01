# threads_poster.py — автопост текстовых постов в Threads + дубль в Telegram.
# Перенесено из social-autopost и встроено в общий автопилот.
#
# Текст генерируется на РЕАЛЬНОМ контенте дня (та же новость/тема, что и в видео),
# а не на абстрактных шаблонных темах — так посты не повторяются и не звучат "ни о чём".
# Основной движок — Groq (console.groq.com, отдельная квота, не трогает Gemini). Gemini —
# только аварийный резерв: у него на бесплатном тарифе жёсткий лимит 20 запросов/сутки на
# модель, который и так расходует основной видео-конвейер — делать его основным здесь рискованно.
#
# БЕЗОПАСНОСТЬ: ключи только из окружения (GitHub Secrets / .env), в коде их нет.
#   GROQ_API_KEY            — основной движок текста (console.groq.com, бесплатно)
#   GEMINI_API_KEY          — резервный движок, если Groq недоступен (тот же ключ, что и для видео —
#                             использовать экономно, квота общая с видео-конвейером)
#   THREADS_USER_ID         — id аккаунта Threads
#   THREADS_ACCESS_TOKEN    — долгоживущий токен (~60 дней)
#   THREADS_TOKEN_EXPIRES   — дата истечения токена (YYYY-MM-DD) для напоминания
#   TELEGRAM_BOT_TOKEN, TELEGRAM_ALERT_CHAT_ID — дубль поста и алерты в Telegram
#   AUTHOR_ROLE, AUTHOR_TELEGRAM, IMAGE_PROBABILITY — оформление (необязательно)
#   PROMO_PROBABILITY (default 0.25), AUTHOR_STORY_PROBABILITY (default 0.12) — как часто
#   в посте есть самопродвижение / отдельная история про автора (раньше было каждый день)
import os
import time
import random
import urllib.parse
from datetime import date
import requests
from dotenv import load_dotenv

load_dotenv()


def _env(key, default=""):
    return (os.getenv(key) or default).strip()


def _env_float(key, default):
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


# ------------------------------------------------------------------
#  Telegram — дубль поста и уведомления
# ------------------------------------------------------------------
def _tg(method, **data):
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=60)
    except requests.RequestException as e:
        print(f"[TG] не отправилось: {e}")


def _tg_alert(text):
    chat = _env("TELEGRAM_ALERT_CHAT_ID")
    if chat:
        _tg("sendMessage", chat_id=chat, text=text)


def _tg_duplicate(text, image_url):
    """Дублирует пост в твой Telegram (тот же чат, что и алерты)."""
    chat = _env("TELEGRAM_ALERT_CHAT_ID")
    if not chat:
        return
    if image_url:
        _tg("sendPhoto", chat_id=chat, photo=image_url, caption=text[:1024])
    else:
        _tg("sendMessage", chat_id=chat, text=text)


# ------------------------------------------------------------------
#  Позиционирование автора (мягкая нативная реклама услуги)
# ------------------------------------------------------------------
def _author_block(strong=True):
    role = _env("AUTHOR_ROLE", "эксперт по автоматизации бизнеса и рутины с помощью нейросетей")
    tg = _env("AUTHOR_TELEGRAM")
    if strong:
        promo = (
            f"\n\nAbout the author: я {role}. Weave in naturally and warmly that I personally BUILD "
            "and SET UP such AI bots and automations for business and social-media account owners who "
            "want their posting and routine done for them. Make the reader curious and think 'I want "
            "the same', not pressured. "
        )
        promo += (f"Insert this exact link once, organically, as where to reach me: {tg}."
                  if tg else "Mention my Telegram from the profile once, organically.")
    else:
        promo = (
            f"\n\nAbout the author: я {role}. At the very end add ONE short, light line that I build and "
            "connect such AI automations for those who want it — friendly, not an ad. "
        )
        if tg:
            promo += f"Include this exact link once, unobtrusively: {tg}."
    return promo


# ------------------------------------------------------------------
#  Промпт: ИНТЕРЕСНО и ЦЕПЛЯЮЩЕ, без пессимизма и запугивания
# ------------------------------------------------------------------
def _base_prompt():
    return (
        "You are a top social-media creator. Write a Threads post in RUSSIAN that is genuinely "
        "INTERESTING, fresh and share-worthy. "
        "Open with a strong curiosity hook in the first line: a surprising fact, an unexpected angle, "
        "or an intriguing question that makes the reader think 'о, не знал(а)' or 'хочу попробовать'. "
        "TONE: energetic, warm, inspiring and helpful. "
        "STRICTLY AVOID: doom and fear ('ты уже без работы', 'ИИ заменит всех', 'ты опоздал'), "
        "aggression, negativity, panic, clichés. Do NOT scare — spark curiosity and excitement instead. "
        "Give ONE concrete, vivid, useful idea or a genuinely wow example about AI/automation that the "
        "reader can picture or use. Make it feel like an insider tip from a friend. "
        "Refer to the reader as 'ты'. Max 498 characters. No emojis (rare, only if truly fitting). "
        "Do not use '*' and do not wrap the text in quotes. Output ONLY the finished post text.\n\nTopic:\n"
    )


def _grounded_prompt(content):
    """Пост на основе РЕАЛЬНОГО контента, который агент уже сгенерировал сегодня для видео
    (та же новость / автоматизация / обзор инструмента) — вместо абстрактной темы 'придумай что-то
    удивительное'. Даёт модели факты, но просит написать самостоятельный нативный пост, а не
    пересказ сценария."""
    title = content.get("title_shorts") or content.get("title_long") or ""
    desc = (content.get("description") or "")[:500]
    script = (content.get("shorts_script") or content.get("long_script") or "")[:800]
    return (
        "You are a top social-media creator. Below is REAL content the channel already made today — "
        "use it as your factual source, but write a Threads post in RUSSIAN that is a native, "
        "standalone post, NOT a copy or summary of the script: build it around the same real hook or "
        "fact, as if explaining the most interesting part fresh to a friend who hasn't seen the video. "
        "Open with a strong curiosity hook in the first line. "
        "TONE: energetic, warm, inspiring and helpful. "
        "STRICTLY AVOID: doom and fear, aggression, negativity, panic, clichés. "
        "Refer to the reader as 'ты'. Max 498 characters. No emojis (rare, only if truly fitting). "
        "Do not use '*' and do not wrap the text in quotes. Output ONLY the finished post text.\n\n"
        f"Заголовок: {title}\n\nОписание: {desc}\n\n"
        f"Сценарий (источник фактов, не копировать дословно):\n{script}"
    )


# Резервные темы — используются, только если сегодняшний контент для видео не сгенерировался
# (сбой Gemini/новостей и т.п.), чтобы Threads всё равно не молчал.
NEWS_THEMES = [
    "One genuinely surprising thing AI can already do right NOW that most people have no idea about — "
    "explain it vividly with a concrete example, so the reader goes 'вау, реально?'.",
    "A practical everyday task that eats people's hours, which AI can now do in seconds — show it "
    "concretely and make the reader want to try it today.",
    "A fresh, positive AI/automation trend and one clever way an ordinary person or small business can "
    "use it to save time or make money — inspiring and doable, not hype.",
    "A little-known but super useful AI trick or tool the reader can start using immediately — "
    "explain the 'how' simply, like a helpful friend sharing a secret.",
]
AUTHOR_THEMES = [
    "A short, warm, believable first-person story: how I built an AI bot that AUTOMATICALLY writes and "
    "publishes content every day on autopilot. Tell it as a concrete mini-case with a satisfying result, "
    "so business and account owners think 'хочу так же' — inspiring, not boastful.",
    "A friendly case story of automating a boring routine for a client with a custom AI bot: the messy "
    "'before', what the bot now does by itself, the time and calm it gives back. Specific and relatable.",
    "A personal, honest story of how learning to build AI automations changed my days and income, and how "
    "I now set them up for people tired of doing everything by hand. Warm and motivating.",
]

_IMAGE_PROMPT_SYS = (
    "You create prompts for eye-catching visual content for Threads/Instagram: bright, positive, modern "
    "images that grab attention and are easy to share. Based on the post text, capture its core idea. "
    "Describe a bright, clean, minimalist image: vivid colors, simple composition, a clever positive "
    "metaphor, a spark of curiosity. Output ONLY the image prompt in English, nothing else."
)


def _pick_prompt(content):
    """Выбирает промпт поста:
    — по умолчанию: реальный факт из контента, который агент уже сгенерировал сегодня для видео;
    — если контента нет (сбой генерации видео) — резервная общая тема;
    — изредка (AUTHOR_STORY_PROBABILITY) — отдельная личная история автора вместо новости;
    — самопродвижение (PROMO_PROBABILITY) добавляется отдельной низкой вероятностью,
      а не через день, как было раньше."""
    if random.random() < _env_float("AUTHOR_STORY_PROBABILITY", 0.12):
        return _base_prompt() + random.choice(AUTHOR_THEMES) + _author_block(strong=True)

    prompt = _grounded_prompt(content) if content else (_base_prompt() + random.choice(NEWS_THEMES))
    if random.random() < _env_float("PROMO_PROBABILITY", 0.25):
        prompt += _author_block(strong=False)
    return prompt


# ------------------------------------------------------------------
#  Gemini (основной текст, тот же движок, что и в сценариях видео) +
#  Groq как резерв, если Gemini недоступен + Pollinations (картинка)
# ------------------------------------------------------------------
def _gemini_chat(system, user):
    key = _env("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY не задан")
    import google.generativeai as genai
    genai.configure(api_key=key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    resp = model.generate_content(f"{system}\n\n{user}")
    return resp.text.strip()


def _groq_chat(system, user):
    key = _env("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY не задан")
    # llama-3.3-70b-versatile отключена Groq для free/developer-тарифа 16.08.2026.
    # Актуальная production-модель: openai/gpt-oss-120b (можно переопределить GROQ_MODEL).
    model = _env("GROQ_MODEL", "openai/gpt-oss-120b")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}], "temperature": 0.9},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _chat(system, user):
    """Groq — основной движок для соцпостов. ВАЖНО: не Gemini, хотя он и пишет сценарии видео
    качественнее — у GEMINI_API_KEY на бесплатном тарифе жёсткий лимит 20 запросов/сутки на
    модель, и его уже расходует основной видео-конвейер (выбор новости + сценарий + иногда
    исследование новых тем автоматизации). Если сделать Gemini основным ещё и здесь, в дни с
    исследованием тем квоты не хватит и упадёт САМ ВИДЕОКОНВЕЙЕР — это куда важнее одного поста.
    Поэтому Groq (отдельная квота, никак не пересекается с видео) — по умолчанию, а Gemini —
    лишь резерв на случай, если у Groq свои перебои."""
    try:
        return _groq_chat(system, user)
    except Exception as e:
        print(f"[THREADS] Groq недоступен ({e}), резерв — Gemini (следи за его дневной квотой)...")
        return _gemini_chat(system, user)


def _generate_text(content=None):
    prompt = _pick_prompt(content)
    return _chat("You are a viral, positive and helpful copywriter.", prompt)[:498]


def _generate_image_url(post_text):
    img_prompt = _chat(_IMAGE_PROMPT_SYS, post_text)
    encoded = urllib.parse.quote(img_prompt)
    seed = random.randint(1, 10_000_000)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={seed}"
    try:
        requests.get(url, timeout=120)  # прогрев, чтобы картинка успела сгенерироваться
    except requests.RequestException:
        pass
    return url


def _youtube_thumb_url(vid_id):
    """Реальная обложка видео, уже выгруженная на YouTube (та же, что делает create_thumbnail
    под сюжет ролика) — она привязана к теме дня куда точнее, чем случайная AI-картинка.
    YouTube отдаёт крошечную серую заглушку, пока превью не обработалось, поэтому проверяем
    размер ответа, а не только код 200."""
    if not vid_id:
        return None
    for name in ("maxresdefault.jpg", "sddefault.jpg", "hqdefault.jpg"):
        url = f"https://i.ytimg.com/vi/{vid_id}/{name}"
        try:
            r = requests.head(url, timeout=10)
            if r.status_code == 200 and int(r.headers.get("content-length") or 0) > 3000:
                return url
        except requests.RequestException:
            continue
    return None


def _pick_image(content, text):
    vid_id = (content or {}).get("_video_id")
    if vid_id:
        url = _youtube_thumb_url(vid_id)
        if url:
            return url
    if random.random() < _env_float("IMAGE_PROBABILITY", 0.55):
        return _generate_image_url(text)
    return None


def generate_post(content=None):
    """Генерирует текст + картинку поста. Общая точка для Threads/Instagram/Telegram, чтобы не
    дублировать запрос к ИИ и не расходиться в смысле между площадками. Картинка — реальная
    обложка видео дня, если оно уже выгружено (content['_video_id']); иначе — резервная AI-картинка."""
    text = _generate_text(content)
    image_url = _pick_image(content, text)
    return text, image_url


def publish(text, image_url):
    """Публикует уже готовый пост в Threads и дублирует в Telegram. Поднимает исключение при
    сбое публикации — генерация (text/image_url) при этом уже успешна и может уйти в другие
    площадки (см. instagram_poster.py) даже если сам Threads недоступен."""
    _post_threads(text, image_url)
    _tg_duplicate(text, image_url)


# ------------------------------------------------------------------
#  Публикация в Threads
# ------------------------------------------------------------------
def _post_threads(text, image_url):
    uid = _env("THREADS_USER_ID")
    token = _env("THREADS_ACCESS_TOKEN")
    base = f"https://graph.threads.net/v1.0/{uid}"
    params = {"access_token": token, "text": text}
    if image_url:
        params["media_type"] = "IMAGE"
        params["image_url"] = image_url
    else:
        params["media_type"] = "TEXT"
    r = requests.post(f"{base}/threads", params=params, timeout=60)
    r.raise_for_status()
    creation_id = r.json()["id"]
    time.sleep(10)  # Threads просит паузу перед публикацией контейнера
    r2 = requests.post(f"{base}/threads_publish",
                       params={"access_token": token, "creation_id": creation_id}, timeout=60)
    r2.raise_for_status()
    return r2.json()


# ------------------------------------------------------------------
#  Напоминание про срок токена Threads
# ------------------------------------------------------------------
def check_token_expiry(warn_days=12):
    """Если до истечения токена Threads осталось <= warn_days — шлёт напоминание в Telegram."""
    exp = _env("THREADS_TOKEN_EXPIRES")
    if not exp:
        return
    try:
        left = (date.fromisoformat(exp) - date.today()).days
    except ValueError:
        return
    if left <= warn_days:
        _tg_alert(
            f"⚠️ Напоминание: токен Threads истекает через {left} дн. (до {exp}).\n"
            "Нужно обновить THREADS_ACCESS_TOKEN, иначе автопост в Threads встанет.\n"
            "Скажи мне «обнови токен threads» — или запусти get_threads_token.py в social-autopost."
        )
        print(f"[THREADS] Напоминание об истечении токена отправлено (осталось {left} дн.)")


# ------------------------------------------------------------------
#  Один пост
# ------------------------------------------------------------------
def post_once(content=None, text=None, image_url=None):
    """Генерирует (если text не передан) и публикует ОДИН пост в Threads + дубль в Telegram.
    content — контент, уже сгенерированный агентом сегодня для видео (shorts_script/title/description,
    и '_video_id' после успешной заливки на YouTube) — если передан, пост строится на реальном факте
    дня, а не на абстрактной теме, а картинкой становится настоящая обложка видео.
    text/image_url — можно передать уже готовый пост (например, тот же, что ушёл в Instagram),
    тогда повторной генерации не будет.

    Возвращает (text, image_url) при успешной ГЕНЕРАЦИИ, даже если сама публикация в Threads не
    удалась (например, истёк токен) — вызывающий код может всё равно отправить готовый пост в
    другие площадки. Возвращает None, если Threads отключён/не настроен и генерация не нужна была
    (text не передан), либо если генерация не удалась.
    Никогда не роняет автопилот; об ошибке шлёт алерт в Telegram."""
    check_token_expiry()
    enabled = _env("THREADS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    configured = bool(_env("THREADS_ACCESS_TOKEN")) and bool(_env("THREADS_USER_ID"))

    if text is None:
        if not enabled:
            print("[THREADS] Отключён (THREADS_ENABLED=false).")
            return None
        if not configured:
            print("[THREADS] Пропуск — не настроены токены Threads.")
            return None
        try:
            text, image_url = generate_post(content)
        except Exception as e:
            print(f"[THREADS] Ошибка генерации: {e}")
            _tg_alert(f"СБОЙ генерации соц-поста: {str(e)[:280]}")
            return None
        print(f"[THREADS] Текст: {text[:80]}...")

    if not enabled or not configured:
        print("[THREADS] Пропуск публикации — отключён или не настроены токены.")
        return text, image_url

    try:
        publish(text, image_url)
        print("[THREADS] Опубликовано ✅")
    except Exception as e:
        detail = getattr(getattr(e, "response", None), "text", "")
        msg = f"{e} | {detail[:200]}"
        print(f"[THREADS] Ошибка публикации: {msg}")
        _tg_alert(f"СБОЙ Threads: {msg[:300]}")

    return text, image_url


if __name__ == "__main__":
    post_once()
