# telegram_intake.py — приём озвучек через Telegram.
# Ты шлёшь боту голосовое/аудио/файл → он сохраняет его как следующий длинный ролик
# из очереди (long_queue.json), а планировщик публикует его по расписанию.
#
# ВАЖНО: нужен ОТДЕЛЬНЫЙ бот (свой токен), т.к. «слушать» сообщения на одном токене
# может только один процесс — иначе конфликт с твоими другими ботами.
import os
import json
import time
import requests
from dotenv import load_dotenv
from paths import dpath

load_dotenv()
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT = str(os.getenv("TELEGRAM_ALERT_CHAT_ID", "")).strip()
QUEUE_FILE = dpath("long_queue.json")
VOICE_DIR = dpath("my_voice")
OFFSET_FILE = dpath("tg_offset.txt")
AUDIO_EXTS = ("mp3", "m4a", "ogg", "wav", "oga")


def _api(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/{method}", json=params, timeout=65)
    return r.json()


def _send(chat_id, text):
    # Telegram лимит ~4096 символов — шлём частями
    for i in range(0, max(1, len(text)), 4000):
        try:
            _api("sendMessage", chat_id=chat_id, text=text[i:i + 4000],
                 disable_web_page_preview=True)
        except Exception:
            pass


def _clean_script(t):
    """Готовит текст к начитке: убирает [ПАУЗА]/markdown — читать вслух как есть."""
    import re
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = t.replace("**", "")
    t = re.sub(r"(?m)^\s*\*\s+", "— ", t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _next_pending_item():
    """Следующий неопубликованный ролик из очереди, у которого ещё нет озвучки."""
    if not os.path.exists(QUEUE_FILE):
        return None
    try:
        q = json.load(open(QUEUE_FILE, encoding="utf-8"))
    except Exception:
        return None
    for it in q:
        if it.get("published"):
            continue
        slug = it["slug"]
        if any(os.path.exists(os.path.join(VOICE_DIR, f"{slug}.{e}")) for e in AUDIO_EXTS):
            continue  # запись уже есть
        return it
    return None


def _download_file(file_id, dest):
    info = _api("getFile", file_id=file_id)
    path = info.get("result", {}).get("file_path")
    if not path:
        return False
    url = f"https://api.telegram.org/file/bot{TG_TOKEN}/{path}"
    r = requests.get(url, timeout=180)
    if r.status_code != 200:
        return False
    os.makedirs(VOICE_DIR, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(r.content)
    return True


def _extract_audio(msg):
    """Возвращает (file_id, ext) для голоса/аудио/файла-аудио, иначе (None, None)."""
    if msg.get("voice"):
        return msg["voice"]["file_id"], "oga"
    if msg.get("audio"):
        a = msg["audio"]
        ext = (a.get("file_name", "") .rsplit(".", 1)[-1].lower()
               if "." in a.get("file_name", "") else "m4a")
        return a["file_id"], (ext if ext in AUDIO_EXTS else "m4a")
    if msg.get("document"):
        d = msg["document"]
        name = d.get("file_name", "").lower()
        if "audio" in d.get("mime_type", "") or name.endswith(tuple("." + e for e in AUDIO_EXTS)):
            ext = name.rsplit(".", 1)[-1] if "." in name else "m4a"
            return d["file_id"], (ext if ext in AUDIO_EXTS else "m4a")
    return None, None


def _handle(msg):
    chat_id = str(msg.get("chat", {}).get("id"))
    if ALLOWED_CHAT and chat_id != ALLOWED_CHAT:
        return  # принимаем только из своего чата
    text = (msg.get("text") or "").strip().lower()

    # Команды текста
    if text in ("/start", "/help", "старт", "привет"):
        _send(chat_id, "Салам! Я собираю озвучки для длинных видео.\n\n"
                       "/next — пришлю текст следующего ролика для начитки.\n"
                       "Затем запиши голос и пришли мне аудио/голосовое — сохраню и опубликую по расписанию.")
        return
    if text in ("/next", "/text", "/текст", "текст"):
        item = _next_pending_item()
        if not item:
            _send(chat_id, "Все ролики из очереди уже озвучены или опубликованы 🎉")
            return
        _send(chat_id, f"🎬 РОЛИК: {item['topic']}\n"
                       f"📅 Выйдет: {item['publish_date']}\n"
                       f"Начитай текст ниже и пришли аудио (можно голосовым). "
                       f"Пометок в скобках нет — читай как есть.\n" + "─" * 18)
        _send(chat_id, _clean_script(item["content"]["long_script"]))
        return

    file_id, ext = _extract_audio(msg)
    if not file_id:
        return  # не команда и не аудио — молчим
    item = _next_pending_item()
    if not item:
        _send(chat_id, "Сейчас нет длинных видео, ожидающих озвучку. Очередь пуста или всё уже записано.")
        return
    dest = os.path.join(VOICE_DIR, f"{item['slug']}.{ext}")
    if _download_file(file_id, dest):
        _send(chat_id, f"✅ Получила запись для «{item['topic'][:45]}» ({item['slug']}).\n"
                       f"Смонтирую и опубликую по расписанию: {item['publish_date']}.")
        print(f"[TG-INTAKE] Сохранено: {dest}")
    else:
        _send(chat_id, "Не удалось скачать файл — попробуй прислать ещё раз.")


def poll_loop():
    """Бесконечный приём сообщений (long-polling). Запускается отдельным потоком из main.py."""
    if not TG_TOKEN:
        return
    offset = 0
    try:
        if os.path.exists(OFFSET_FILE):
            offset = int(open(OFFSET_FILE).read().strip() or 0)
    except Exception:
        offset = 0
    print("[TG-INTAKE] Слушаю Telegram — жду озвучки...")
    while True:
        try:
            res = _api("getUpdates", offset=offset, timeout=50)
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                m = upd.get("message") or upd.get("channel_post")
                if m:
                    _handle(m)
            try:
                open(OFFSET_FILE, "w").write(str(offset))
            except Exception:
                pass
        except Exception as e:
            print(f"[TG-INTAKE] Ошибка опроса (не критично): {e}")
            time.sleep(5)


if __name__ == "__main__":
    poll_loop()
