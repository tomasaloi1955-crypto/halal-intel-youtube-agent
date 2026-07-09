# threads_poster.py — автопост текстовых постов в Threads + дубль в Telegram.
# Перенесено из social-autopost и встроено в общий автопилот.
#
# БЕЗОПАСНОСТЬ: ключи только из окружения (GitHub Secrets / .env), в коде их нет.
#   GROQ_API_KEY            — генерация текста (console.groq.com, бесплатно)
#   THREADS_USER_ID         — id аккаунта Threads
#   THREADS_ACCESS_TOKEN    — долгоживущий токен (~60 дней)
#   THREADS_TOKEN_EXPIRES   — дата истечения токена (YYYY-MM-DD) для напоминания
#   TELEGRAM_BOT_TOKEN, TELEGRAM_ALERT_CHAT_ID — дубль поста и алерты в Telegram
#   AUTHOR_ROLE, AUTHOR_TELEGRAM, IMAGE_PROBABILITY — оформление (необязательно)
import os
import time
import random
import urllib.parse
from datetime import datetime, date
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


# Интересные, полезные, позитивные темы (охват без негатива)
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


def _pick_theme():
    """Чётный день года — интересные факты/польза, нечётный — история про автора."""
    if datetime.now().timetuple().tm_yday % 2 == 0:
        return random.choice(NEWS_THEMES), False
    return random.choice(AUTHOR_THEMES), True


# ------------------------------------------------------------------
#  Groq (текст) + Pollinations (картинка)
# ------------------------------------------------------------------
def _groq_chat(system, user):
    key = _env("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY не задан")
    model = _env("GROQ_MODEL", "llama-3.3-70b-versatile")
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


def _generate_text():
    theme, is_author = _pick_theme()
    topic = _base_prompt() + theme + _author_block(is_author)
    return _groq_chat("You are a viral, positive and helpful copywriter.", topic)[:498]


def _generate_image_url(post_text):
    img_prompt = _groq_chat(_IMAGE_PROMPT_SYS, post_text)
    encoded = urllib.parse.quote(img_prompt)
    seed = random.randint(1, 10_000_000)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={seed}"
    try:
        requests.get(url, timeout=120)  # прогрев, чтобы картинка успела сгенерироваться
    except requests.RequestException:
        pass
    return url


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
def post_once():
    """Генерирует и публикует ОДИН пост в Threads + дубль в Telegram.
    Никогда не роняет автопилот; об ошибке шлёт алерт в Telegram."""
    check_token_expiry()

    if _env("THREADS_ENABLED", "true").lower() not in ("1", "true", "yes", "on"):
        print("[THREADS] Отключён (THREADS_ENABLED=false).")
        return False
    if not _env("THREADS_ACCESS_TOKEN") or not _env("THREADS_USER_ID") or not _env("GROQ_API_KEY"):
        print("[THREADS] Пропуск — не настроены токены/ключи.")
        return False
    try:
        text = _generate_text()
        print(f"[THREADS] Текст: {text[:80]}...")
        use_image = random.random() < _env_float("IMAGE_PROBABILITY", 0.55)
        image_url = _generate_image_url(text) if use_image else None
        _post_threads(text, image_url)
        print("[THREADS] Опубликовано ✅")
        _tg_duplicate(text, image_url)  # дубль в Telegram
        return True
    except Exception as e:
        detail = getattr(getattr(e, "response", None), "text", "")
        msg = f"{e} | {detail[:200]}"
        print(f"[THREADS] Ошибка публикации: {msg}")
        _tg_alert(f"СБОЙ Threads: {msg[:300]}")
        return False


if __name__ == "__main__":
    post_once()
