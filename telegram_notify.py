# telegram_notify.py — уведомления в Telegram (алерты о сбоях + успехах автопилота)
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_ALERT_CHAT_ID", "")


def notify(text):
    """Шлёт сообщение в Telegram. Тихо выходит, если токен/chat_id не заданы."""
    if not TG_TOKEN or not TG_CHAT:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text, "disable_web_page_preview": True},
            timeout=15,
        )
        return r.ok
    except Exception as e:
        print(f"[TG] Алерт не отправлен: {e}")
        return False


def alert_fail(stage, reason):
    """Алерт о сбое — чтобы ты сразу узнала, а не через неделю тишины."""
    notify(f"🔴 СБОЙ: {stage}\nПричина: {reason}\nПроверь агента «Халяль Интеллидженс».")


def alert_ok(text):
    """Короткое уведомление об успешной публикации."""
    notify(f"✅ {text}")


CAPTION_LIMIT = 1024  # больше Telegram в подпись к фото/видео не берёт


def _send_file(method, field, path, caption=None):
    try:
        with open(path, "rb") as f:
            data = {"chat_id": TG_CHAT}
            if caption:
                data["caption"] = caption
            r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/{method}",
                              data=data, files={field: f}, timeout=120)
        if not r.ok:
            print(f"[TG] {method} не прошёл: {r.text[:200]}")
        return r.ok
    except Exception as e:
        print(f"[TG] {method} не отправлен: {e}")
        return False


def send_post(text, photo=None, video=None):
    """Пост как он выглядел бы в канале: фото (или видео, если фото нет) с текстом
    в подписи, следом видео. Длинный текст в подпись не влезает — тогда медиа,
    а текст отдельным сообщением."""
    if not TG_TOKEN or not TG_CHAT:
        return False
    fits = len(text) <= CAPTION_LIMIT
    if photo:
        first = ("sendPhoto", "photo", photo)
    elif video:
        first, video = ("sendVideo", "video", video), None
    else:
        first = None
    if first and _send_file(*first, text if fits else None) and fits:
        text = None
    if text:
        notify(text)
    if video:
        _send_file("sendVideo", "video", video)
    return True
