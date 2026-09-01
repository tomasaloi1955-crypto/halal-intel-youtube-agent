# instagram_poster.py — автопост в Instagram (Feed, фото + подпись) через Instagram Graph API.
#
# Переиспользует тот же текст и картинку, что уже сгенерированы для Threads
# (generate_post() в threads_poster.py) — чтобы не тратить лишний вызов ИИ и чтобы смысл
# поста не расходился между площадками. Может и сгенерировать сам, если вызван отдельно.
#
# НАСТРОЙКА (один раз, в Meta for Developers — по-другому Instagram Graph API не выдаёт токен):
#   1. Instagram-аккаунт должен быть переведён в Business или Creator и привязан
#      к Facebook-странице (Настройки Instagram → Аккаунт → Переключиться на профессиональный).
#   2. На developers.facebook.com создать приложение, добавить продукт "Instagram Graph API".
#   3. В Graph API Explorer получить User Access Token с правами:
#      instagram_basic, instagram_content_publish, pages_read_engagement, pages_show_list.
#   4. Обменять его на долгоживущий токен (~60 дней):
#      GET https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token
#          &client_id=...&client_secret=...&fb_exchange_token=<короткий_токен>
#   5. Узнать IG_USER_ID: GET /me/accounts → id страницы → затем
#      GET /{page-id}?fields=instagram_business_account&access_token=<токен>
#   6. Положить IG_USER_ID и IG_ACCESS_TOKEN в .env / GitHub Secrets.
#
# БЕЗОПАСНОСТЬ: ключи только из окружения (GitHub Secrets / .env), в коде их нет.
#   IG_USER_ID        — id Instagram Business/Creator аккаунта
#   IG_ACCESS_TOKEN   — долгоживущий токен с правами instagram_content_publish
#   IG_TOKEN_EXPIRES  — дата истечения токена (YYYY-MM-DD) для напоминания в Telegram
#   IG_ENABLED        — "false" чтобы отключить (по умолчанию включён)
import os
import time
from datetime import date
import requests
from dotenv import load_dotenv
from telegram_notify import alert_fail, notify

load_dotenv()


def _env(key, default=""):
    return (os.getenv(key) or default).strip()


def check_token_expiry(warn_days=12):
    """Если до истечения токена Instagram осталось <= warn_days — шлёт напоминание в Telegram."""
    exp = _env("IG_TOKEN_EXPIRES")
    if not exp:
        return
    try:
        left = (date.fromisoformat(exp) - date.today()).days
    except ValueError:
        return
    if left <= warn_days:
        notify(
            f"⚠️ Напоминание: токен Instagram истекает через {left} дн. (до {exp}).\n"
            "Нужно обновить IG_ACCESS_TOKEN, иначе автопост в Instagram встанет."
        )
        print(f"[INSTAGRAM] Напоминание об истечении токена отправлено (осталось {left} дн.)")


def _post_instagram(caption, image_url):
    """Instagram Content Publishing API: сначала создаём медиа-контейнер с картинкой и подписью,
    потом публикуем его. Instagram Feed без изображения не публикуется в принципе."""
    uid = _env("IG_USER_ID")
    token = _env("IG_ACCESS_TOKEN")
    base = f"https://graph.facebook.com/v19.0/{uid}"
    r = requests.post(f"{base}/media", params={
        "access_token": token, "image_url": image_url, "caption": caption,
    }, timeout=60)
    r.raise_for_status()
    creation_id = r.json()["id"]
    time.sleep(5)  # даём Instagram время скачать и обработать картинку перед публикацией
    r2 = requests.post(f"{base}/media_publish",
                       params={"access_token": token, "creation_id": creation_id}, timeout=60)
    r2.raise_for_status()
    return r2.json()


def post_once(content=None, text=None, image_url=None):
    """Публикует ОДИН пост в Instagram.
    Если text/image_url переданы (обычно — уже сгенерированные threads_poster.generate_post
    для того же дня) — публикует их как есть, без повторного обращения к ИИ.
    Если не переданы — генерирует сам, тем же движком, что и Threads (реальный факт дня).
    Instagram Feed не публикуется без картинки — если её нет, пост пропускается, а не падает.
    Никогда не роняет автопилот; об ошибке шлёт алерт в Telegram."""
    check_token_expiry()

    if _env("IG_ENABLED", "true").lower() not in ("1", "true", "yes", "on"):
        print("[INSTAGRAM] Отключён (IG_ENABLED=false).")
        return False
    if not _env("IG_ACCESS_TOKEN") or not _env("IG_USER_ID"):
        print("[INSTAGRAM] Пропуск — не настроены IG_USER_ID / IG_ACCESS_TOKEN "
              "(см. инструкцию в шапке instagram_poster.py).")
        return False

    try:
        if text is None:
            from threads_poster import generate_post
            text, image_url = generate_post(content)
        if not image_url:
            print("[INSTAGRAM] Пропуск — нет картинки (Instagram Feed без фото не публикуется).")
            return False
        print(f"[INSTAGRAM] Текст: {text[:80]}...")
        _post_instagram(text[:2200], image_url)
        print("[INSTAGRAM] Опубликовано ✅")
        return True
    except Exception as e:
        detail = getattr(getattr(e, "response", None), "text", "")
        msg = f"{e} | {detail[:200]}"
        print(f"[INSTAGRAM] Ошибка публикации: {msg}")
        alert_fail("Instagram — публикация", msg[:200])
        return False


if __name__ == "__main__":
    post_once()
