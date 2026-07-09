# threads_poster.py — автопост текстовых постов в Threads.
# Перенесено из проекта social-autopost и встроено в общий автопилот.
#
# БЕЗОПАСНОСТЬ: ключи только из окружения (GitHub Secrets / .env), в коде их нет.
#   GROQ_API_KEY            — генерация текста (console.groq.com, бесплатно)
#   THREADS_USER_ID         — id аккаунта Threads
#   THREADS_ACCESS_TOKEN    — долгоживущий токен (~60 дней, get_threads_token.py)
#   AUTHOR_ROLE, AUTHOR_TELEGRAM, IMAGE_PROBABILITY — оформление постов (необязательно)
import os
import time
import random
import urllib.parse
import requests
from datetime import datetime
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
#  Темы + позиционирование автора (как в social-autopost)
# ------------------------------------------------------------------
def _author_block(strong=True):
    role = _env("AUTHOR_ROLE", "эксперт по автоматизации бизнеса и рутины с помощью нейросетей")
    tg = _env("AUTHOR_TELEGRAM")
    if strong:
        promo = (
            f"\n\nAbout the author: я {role}. Naturally weave in my personal brand as an "
            "AI-automation expert. Make clear, but subtly, that I personally BUILD and SET UP "
            "such AI bots and automations FOR OTHER PEOPLE — for business owners and social-media "
            "account owners who want their posting and routine done automatically. "
        )
        promo += (f"Insert this exact link verbatim into the text once, organically: {tg}. Not spammy."
                  if tg else
                  "Mention my Telegram from the profile header once, organically. Not spammy.")
    else:
        promo = (
            f"\n\nAbout the author: я {role}. At the very end add just ONE short, soft line that "
            "I build and connect such AI automation bots for those who want it — keep it light, "
            "do NOT turn the news into an ad. "
        )
        if tg:
            promo += f"Include this exact link once, unobtrusively: {tg}."
    return promo


def _base_prompt():
    return (
        "Create a text that begins with a vivid, provocative phrase that elicits an immediate "
        "emotional response and prompts action (comment, like, repost, save). Use a sharp, bold "
        "tone, touch on a taboo topic, a common myth or a painful societal issue. Present the idea "
        "so the reader either strongly agrees or is outraged from the very first words. Add an "
        "unexpected twist or an intriguing question that compels them to read to the end. "
        "Be human, not formal, you can refer to the reader as 'ты'. Write everything in Russian. "
        "No more than 498 characters. Do not use emojis (only very rarely if truly on topic). "
        "Do not use '*' and do not wrap the text in quotes. Output ONLY the finished post text, "
        "nothing else.\n\nTopic:\n"
    )


NEWS_THEMES = [
    "News about neural networks and what's happening in the world of AI right now: a fresh trend, "
    "a breakthrough or a shift; what it means for business and ordinary people, who will win and "
    "who will be left behind.",
    "A sharp take on the latest AI trend and how fast automation is changing work and money; why "
    "most people are dangerously late to it.",
    "What the near future holds with AI: which jobs and routines will be automated first, and how "
    "businesses that adopt AI now will crush those that wait.",
]
AUTHOR_THEMES = [
    "A first-person real story: how I built an AI bot that every day AUTOMATICALLY writes and "
    "publishes posts to Threads, Instagram and Telegram, fully on autopilot. Tell it as a concrete "
    "mini-case: what the routine was before, what changed, the result. Make business and account "
    "owners think 'I want the same'.",
    "A short, believable case story of automating a boring routine for a business or an account "
    "owner with a custom AI bot: the problem before, what the bot now does by itself, the time and "
    "money it saves. Specific and real, not hype.",
    "A personal story of how learning to build AI bots changed my life and income, and how I now set "
    "up these automations for clients tired of doing everything by hand. Honest and inspiring.",
]

_IMAGE_PROMPT_SYS = (
    "You create prompts for visual content for Threads/Instagram: bright images that grab attention "
    "and are easy to share. Based on the given post text, highlight its core meaning/emotion. Describe "
    "a bright, modern, minimalist image: saturated colors, simple composition, symbolic metaphors. "
    "Output ONLY the image prompt in English, nothing else."
)


def _pick_theme():
    """Чётный день года — новости, нечётный — история про автора."""
    if datetime.now().timetuple().tm_yday % 2 == 0:
        return random.choice(NEWS_THEMES), False
    return random.choice(AUTHOR_THEMES), True


# ------------------------------------------------------------------
#  Groq (генерация текста) + Pollinations (картинка)
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
    return _groq_chat("You are a viral copywriter for social media.", topic)[:498]


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


def post_once():
    """Генерирует и публикует ОДИН пост в Threads. Никогда не роняет автопилот.
    Возвращает True при успехе, False при пропуске/ошибке."""
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
        return True
    except Exception as e:
        detail = getattr(getattr(e, "response", None), "text", "")
        print(f"[THREADS] Ошибка публикации: {e} | {detail[:200]}")
        return False


if __name__ == "__main__":
    post_once()
