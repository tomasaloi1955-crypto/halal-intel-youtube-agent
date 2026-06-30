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
