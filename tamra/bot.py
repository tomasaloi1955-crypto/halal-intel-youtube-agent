# bot.py — Telegram-бот Tamra School: сырые клипы + озвучка → готовый ролик «День N».
#
# Как пользоваться (всё в чате с ботом):
#   1. Присылаешь клипы и/или фото (скриншоты экрана тоже) — в том порядке, в каком они
#      должны идти в ролике.
#   2. Присылаешь озвучку: голосовое или аудиофайл. Можно добавить текстовую заметку —
#      «сегодня делала тест по математике», нейросеть учтёт её в хуке и подписи.
#   3. Бот склеивает ролик под длину озвучки, ставит плашку «ДЕНЬ N», хук, субтитры,
#      призыв в конце, делает обложку и пишет подпись с хэштегами — и присылает превью.
#   4. Кнопка «✅ Опубликовать» — ролик уходит в Instagram, YouTube и TikTok.
#      «🔁 Другой хук» — нейросеть перепишет тексты. «❌ Удалить» — черновик в корзину.
#      Свой хук/подпись: напиши «хук: …» или «подпись: …».
#
# Только озвучка, без клипов — кадры подбираются со стока (tamra/stock.py: руки, ноутбук,
# стол; каждый клип проверяет ИИ — лиц быть не должно).
#
# Сборка стартует сама, когда есть озвучка и минуту ничего не приходило.
# Без озвучки — напиши «готово», ролик соберётся немым, с хуком и призывом.
#
# Окружение:
#   TAMRA_TG_TOKEN    — токен ОТДЕЛЬНОГО бота от @BotFather (не тот, что у Халяль Интеллидженс)
#   TAMRA_TG_CHAT_ID  — твой chat id; если не задан, хозяином станет первый, кто напишет /start
#   GEMINI_API_KEY, ELEVENLABS_API_KEY (необязательно) + ключи площадок (см. tamra/publish.py)
#
# Запуск: python -m tamra.bot          — постоянно (сервер, Render)
#         python -m tamra.bot --once   — один проход (GitHub Actions по расписанию)
import os
import sys
import json
import time
import shutil
import uuid
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

from paths import dpath  # noqa: E402
from tamra import montage, writer, stock  # noqa: E402

TOKEN = os.getenv("TAMRA_TG_TOKEN", "")
STATE_FILE = dpath("tamra_state.json")
WORK = dpath(os.path.join("output", "tamra"))
IDLE_BEFORE_BUILD = 60       # сек тишины после последнего файла — и можно собирать
TG_DOWNLOAD_LIMIT = 20 * 1024 * 1024  # Bot API не отдаёт файлы тяжелее 20 МБ

HELP = (
    "Ассаляму алейкум! Я собираю ролики «День N» для Tamra School.\n\n"
    "1️⃣ Пришли клипы и/или фото (скриншоты тоже) — в нужном порядке.\n"
    "2️⃣ Пришли озвучку — голосовым или аудиофайлом.\n"
    "3️⃣ По желанию — заметку текстом: о чём сегодняшний день.\n\n"
    "Нет своих клипов — пришли только озвучку: подберу кадры сама "
    "(руки, ноутбук, рабочий стол — без лиц).\n\n"
    "Я склею ролик под озвучку, добавлю «ДЕНЬ N», хук, субтитры, обложку и подпись "
    "и пришлю превью. Дальше — кнопка «Опубликовать».\n\n"
    "Команды:\n"
    "• готово — собрать сейчас (можно и без озвучки)\n"
    "• хук: текст — свой хук на экран\n"
    "• подпись: текст — своя подпись\n"
    "• день 12 — поставить номер дня\n"
    "• сброс — очистить присланное\n\n"
    "Видео присылай обычным видео, не файлом — так Telegram его сожмёт (боту доступно до 20 МБ)."
)


# ── состояние ──────────────────────────────────────────────────────────────

def _empty_batch():
    return {"media": [], "voice": None, "notes": [], "hook": None, "caption": None, "updated": 0}


def load_state():
    try:
        st = json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:
        st = {}
    st.setdefault("offset", 0)
    st.setdefault("owner", None)
    st.setdefault("day", 1)
    st.setdefault("batch", _empty_batch())
    st.setdefault("draft", None)
    st.setdefault("history", [])
    st.setdefault("stock_used", [])
    return st


def save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


# ── Telegram ───────────────────────────────────────────────────────────────

def api(method, files=None, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    if files:
        data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}
        r = requests.post(url, data=data, files=files, timeout=300)
    else:
        r = requests.post(url, json=params, timeout=65)
    return r.json()


def send(chat, text, **kw):
    for i in range(0, max(1, len(text)), 4000):
        api("sendMessage", chat_id=chat, text=text[i:i + 4000], disable_web_page_preview=True, **kw)


def download(file_id, dest):
    info = api("getFile", file_id=file_id)
    path = info.get("result", {}).get("file_path")
    if not path:
        raise RuntimeError(f"Telegram не отдал файл: {info.get('description', info)}")
    r = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}", timeout=300)
    r.raise_for_status()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(r.content)
    return dest


def _ext(name, default):
    return name.rsplit(".", 1)[-1].lower() if name and "." in name else default


def classify(msg):
    """Что за вложение: ("video"|"photo"|"voice", file_id, ext, size) или None."""
    if msg.get("video"):
        v = msg["video"]
        return "video", v["file_id"], _ext(v.get("file_name"), "mp4"), v.get("file_size", 0)
    if msg.get("video_note"):
        v = msg["video_note"]
        return "video", v["file_id"], "mp4", v.get("file_size", 0)
    if msg.get("animation"):
        v = msg["animation"]
        return "video", v["file_id"], "mp4", v.get("file_size", 0)
    if msg.get("photo"):
        p = msg["photo"][-1]  # самое большое разрешение
        return "photo", p["file_id"], "jpg", p.get("file_size", 0)
    if msg.get("voice"):
        v = msg["voice"]
        return "voice", v["file_id"], "ogg", v.get("file_size", 0)
    if msg.get("audio"):
        a = msg["audio"]
        return "voice", a["file_id"], _ext(a.get("file_name"), "m4a"), a.get("file_size", 0)
    if msg.get("document"):
        d = msg["document"]
        mime, name = d.get("mime_type", ""), d.get("file_name", "")
        kind = ("video" if mime.startswith("video/") else "photo" if mime.startswith("image/")
                else "voice" if mime.startswith("audio/") else None)
        if kind:
            default = {"video": "mp4", "photo": "jpg", "voice": "m4a"}[kind]
            return kind, d["file_id"], _ext(name, default), d.get("file_size", 0)
    return None


# ── сборка и публикация ────────────────────────────────────────────────────

def _fetch_sources(spec, workdir):
    voice = None
    if spec.get("voice"):
        v = spec["voice"]
        voice = os.path.join(workdir, "src", f"voice.{v['ext']}")
        if not os.path.exists(voice):
            download(v["file_id"], voice)
    media = []
    for i, m in enumerate(spec["media"]):
        p = download(m["file_id"], os.path.join(workdir, "src", f"{i:02d}.{m['ext']}"))
        media.append({"path": p, "kind": m["kind"]})
    if not media:
        media = _stock_media(spec, voice, os.path.join(workdir, "src"))
    return media, voice


def _stock_media(spec, voice, srcdir):
    """Клипов нет — берём сток. Подобранные клипы запоминаются в черновике, чтобы
    пересборка (другой хук, публикация) дала тот же видеоряд без повторной проверки."""
    if spec.get("stock_clips"):
        return [{"path": stock.download(c["url"], os.path.join(srcdir, f"stock_{c['id']}.mp4")),
                 "kind": "video"} for c in spec["stock_clips"]]
    seconds = montage.duration(voice) if voice else 15
    count = max(3, min(8, int(seconds / 4) + 1))  # новый кадр примерно каждые 4 секунды
    picked = stock.pick(count, spec.get("stock_exclude", []), srcdir,
                        queries=(spec.get("texts") or {}).get("stock_queries"))
    if not picked:
        raise RuntimeError("не нашла подходящих стоковых кадров без лиц — пришли свои клипы")
    spec["stock_clips"] = [{"id": c["id"], "url": c["url"]} for c in picked]
    return [{"path": c["path"], "kind": "video"} for c in picked]


def render(draft):
    """Собирает видео черновика (или берёт уже собранное). Возвращает (mp4, обложка)."""
    workdir = os.path.join(WORK, draft["id"])
    out = os.path.join(workdir, f"tamra_day{draft['day']}.mp4")
    cover = os.path.splitext(out)[0] + "_cover.jpg"
    if os.path.exists(out) and os.path.exists(cover) and draft.get("rendered_hook") == draft["texts"]["hook"]:
        return out, cover
    media, voice = _fetch_sources(draft, workdir)
    montage.build(media, voice, draft["day"], draft["texts"]["hook"],
                  draft["texts"]["subtitles"], os.path.join(workdir, "work"), out)
    draft["rendered_hook"] = draft["texts"]["hook"]
    return out, cover


def _write_texts(draft):
    voice = None
    if draft.get("voice"):
        workdir = os.path.join(WORK, draft["id"])
        v = draft["voice"]
        voice = os.path.join(workdir, "src", f"voice.{v['ext']}")
        if not os.path.exists(voice):
            download(v["file_id"], voice)
    texts = writer.write(draft["day"], draft["notes"], voice)
    if draft.get("hook_override"):
        texts["hook"] = draft["hook_override"]
    if draft.get("caption_override"):
        texts["caption"] = draft["caption_override"]
    draft["texts"] = texts


def _buttons():
    return {"inline_keyboard": [[
        {"text": "✅ Опубликовать", "callback_data": "pub"},
        {"text": "🔁 Другой хук", "callback_data": "redo"},
        {"text": "❌ Удалить", "callback_data": "del"},
    ]]}


def send_preview(chat, draft):
    video, cover = render(draft)
    t = draft["texts"]
    with open(cover, "rb") as f:
        api("sendPhoto", chat_id=chat, caption=f"Обложка · День {draft['day']}",
            files={"photo": ("cover.jpg", f, "image/jpeg")})
    with open(video, "rb") as f:
        res = api("sendVideo", chat_id=chat, supports_streaming=True, width=1080, height=1920,
                  caption=f"🎬 День {draft['day']}\nХук: {t['hook']}\nYouTube: {t['title']}"[:1024],
                  reply_markup=_buttons(),
                  files={"video": (os.path.basename(video), f, "video/mp4")})
    if not res.get("ok"):
        send(chat, f"Не смогла прислать видео: {res.get('description')}")
    send(chat, "Подпись (для копирования):\n\n" + writer.full_caption(t))


def build_draft(st, chat):
    b = st["batch"]
    if not b["media"] and not b["voice"]:
        send(chat, "Пришли озвучку (и, если есть, свои клипы или фото) — потом соберу ролик.")
        return
    if st.get("draft"):
        send(chat, "Прошлый неопубликованный черновик заменяю новым.")
        _drop_draft(st)
    draft = {"id": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4],
             "day": st["day"], "media": b["media"], "voice": b["voice"], "notes": b["notes"],
             "hook_override": b.get("hook"), "caption_override": b.get("caption"),
             "stock_exclude": st["stock_used"][-300:]}
    st["batch"] = _empty_batch()
    st["draft"] = draft
    what = (f"{len(draft['media'])} клип(ов)" if draft["media"]
            else "подбираю кадры с руками и ноутбуком")
    send(chat, f"⏳ Собираю «День {draft['day']}»: {what}"
               f"{', с озвучкой' if draft['voice'] else ', без озвучки'}. Это 1–3 минуты…")
    try:
        _write_texts(draft)
        send_preview(chat, draft)
    except Exception as e:
        print(f"[TAMRA] Сборка не удалась: {e}")
        send(chat, f"🔴 Не получилось собрать ролик: {str(e)[:300]}\n"
                   "Черновик сохранён — напиши «готово», чтобы попробовать ещё раз.")
        st["batch"] = {**_empty_batch(), "media": draft["media"], "voice": draft["voice"],
                       "notes": draft["notes"], "hook": draft.get("hook_override"),
                       "caption": draft.get("caption_override"),
                       "updated": time.time(), "auto_failed": True}  # сама не повторяю
        st["draft"] = None


def _drop_draft(st):
    d = st.get("draft")
    if d:
        shutil.rmtree(os.path.join(WORK, d["id"]), ignore_errors=True)
    st["draft"] = None


def publish_draft(st, chat):
    from tamra.publish import publish_all
    d = st.get("draft")
    if not d:
        send(chat, "Нет черновика для публикации. Пришли клипы и озвучку.")
        return
    # Снимаем черновик ДО публикации: если процесс упадёт посередине, повторный запуск
    # не опубликует тот же ролик второй раз.
    st["draft"] = None
    save_state(st)
    send(chat, f"🚀 Публикую «День {d['day']}»…")
    try:
        video, _ = render(d)
        results = publish_all(video, d["texts"], writer.full_caption(d["texts"]))
    except Exception as e:
        st["draft"] = d
        send(chat, f"🔴 Не получилось подготовить видео: {str(e)[:300]}. Черновик на месте — "
                   "нажми «Опубликовать» ещё раз.")
        return
    send(chat, f"Итог «День {d['day']}»:\n" + "\n".join(f"{k}: {v}" for k, v in results.items()))
    if any(v.startswith("✅") for v in results.values()):
        st["history"] = (st["history"] + [{
            "day": d["day"], "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "hook": d["texts"]["hook"], "results": results}])[-90:]
        st["day"] = max(st["day"], d["day"] + 1)
        st["stock_used"] = (st["stock_used"] + [c["id"] for c in d.get("stock_clips", [])])[-300:]
        shutil.rmtree(os.path.join(WORK, d["id"]), ignore_errors=True)
    else:
        st["draft"] = d
        send(chat, "Ни одна площадка не приняла ролик — черновик сохранён.")


# ── обработка сообщений ────────────────────────────────────────────────────

def _is_owner(st, chat, text):
    allowed = os.getenv("TAMRA_TG_CHAT_ID", "").strip() or st.get("owner")
    if allowed:
        return str(chat) == str(allowed)
    if text.startswith("/start"):
        st["owner"] = str(chat)  # первый, кто написал /start, — хозяин бота
        return True
    return False


def handle_message(st, msg):
    chat = msg["chat"]["id"]
    text = (msg.get("text") or msg.get("caption") or "").strip()
    low = text.lower()
    if not _is_owner(st, chat, low):
        return
    b = st["batch"]

    b.pop("auto_failed", None)  # что-то новое пришло — можно снова собирать автоматически
    att = classify(msg)
    if att:
        kind, fid, ext, size = att
        if size and size > TG_DOWNLOAD_LIMIT:
            # без этого флага бот собрал бы ролик на стоке, хотя ты ждёшь своё видео
            b["oversize"] = True
            send(chat, f"Файл {size // (1024 * 1024)} МБ — боту доступно до 20 МБ, этот не взяла. "
                       "Пришли его сжатым (при отправке выбери качество 480p/720p) или обрежь покороче. "
                       "Или напиши «готово» — соберу на стоковых кадрах.")
            return
        if kind == "voice":
            if b["voice"]:
                send(chat, "Озвучку заменила на новую.")
            b["voice"] = {"file_id": fid, "ext": ext}
        else:
            b["media"].append({"kind": kind, "file_id": fid, "ext": ext})
        if text:  # подпись к видео — тоже заметка
            b["notes"].append(text)
        # время отправки, а не обработки: в Actions сообщение могло прийти минуты назад,
        # и тогда собирать можно уже в этом же проходе
        b["updated"] = msg.get("date", time.time())
        group = msg.get("media_group_id")
        if group and group == b.get("last_group"):
            return  # альбом приходит пачкой сообщений — отвечаем один раз, на первое
        b["last_group"] = group
        got = f"клипов/фото: {len(b['media'])}, озвучка: {'есть' if b['voice'] else 'нет'}"
        tail = ("\nСвоих клипов нет — подберу кадры с руками и ноутбуком сама. "
                "Хочешь свои — пришли их в ближайшую минуту." if kind == "voice" and not b["media"] else "")
        send(chat, f"👌 Приняла ({got}).{tail}")
        return

    if not text:
        return
    if low in ("/start", "/help", "помощь", "help", "/старт", "старт", "/помощь"):
        send(chat, HELP)
        return
    if low in ("готово", "/go", "собрать", "/build", "собери"):
        build_draft(st, chat)
        return
    if low in ("сброс", "/reset", "отмена", "/cancel"):
        st["batch"] = _empty_batch()
        _drop_draft(st)
        send(chat, "Очистила. Присылай новые клипы и озвучку.")
        return
    if low in ("ок", "да", "публикуй", "опубликовать", "/publish"):
        publish_draft(st, chat)
        return
    if low.startswith(("день ", "/day ")):
        try:
            st["day"] = max(1, int(low.split()[1]))
            if st.get("draft"):
                st["draft"]["day"] = st["day"]
                st["draft"].pop("rendered_hook", None)
            send(chat, f"Следующий ролик будет «День {st['day']}».")
        except (ValueError, IndexError):
            send(chat, "Напиши так: день 12")
        return
    for prefix, key, field in (("хук:", "hook", "hook_override"), ("подпись:", "caption", "caption_override")):
        if low.startswith(prefix):
            value = text[len(prefix):].strip()
            d = st.get("draft")
            if d:
                d[field] = value
                d["texts"][key] = value
                send(chat, "Обновила, пересобираю превью…")
                try:
                    send_preview(chat, d)
                except Exception as e:
                    send(chat, f"🔴 Не получилось пересобрать: {str(e)[:300]}")
            else:
                b[key] = value
                b["updated"] = time.time()
                send(chat, f"Запомнила {'хук' if key == 'hook' else 'подпись'} для следующего ролика.")
            return
    if text.startswith("/"):
        send(chat, "Не знаю такой команды. Напиши «помощь» — пришлю список.")
        return
    b["notes"].append(text)
    b["updated"] = msg.get("date", time.time())
    send(chat, "📝 Заметку учту в хуке и подписи.")


def handle_callback(st, cq):
    chat = cq["message"]["chat"]["id"]
    api("answerCallbackQuery", callback_query_id=cq["id"])
    if not _is_owner(st, chat, ""):
        return
    action = cq.get("data")
    d = st.get("draft")
    if action == "pub":
        publish_draft(st, chat)
    elif action == "del":
        _drop_draft(st)
        send(chat, "Черновик удалён.")
    elif action == "redo" and d:
        d.pop("hook_override", None)
        send(chat, "Переписываю тексты…")
        try:
            _write_texts(d)
            send_preview(chat, d)
        except Exception as e:
            send(chat, f"🔴 Не получилось: {str(e)[:300]}")
    elif not d:
        send(chat, "Этот черновик уже опубликован или удалён.")


def maybe_autobuild(st):
    """Озвучка на месте (клипы — свои или со стока), минуту ничего не приходило — собираем."""
    b = st["batch"]
    chat = os.getenv("TAMRA_TG_CHAT_ID", "").strip() or st.get("owner")
    if (chat and b["voice"] and not b.get("auto_failed")
            and (b["media"] or not b.get("oversize"))
            and time.time() - b["updated"] >= IDLE_BEFORE_BUILD):
        build_draft(st, chat)


def process(st, updates):
    for upd in updates:
        st["offset"] = upd["update_id"] + 1
        try:
            if upd.get("message"):
                handle_message(st, upd["message"])
            elif upd.get("callback_query"):
                handle_callback(st, upd["callback_query"])
        except Exception as e:
            print(f"[TAMRA] Ошибка обработки сообщения: {e}")
        save_state(st)


def poll_once():
    """Один проход: забрать накопившиеся сообщения, при необходимости собрать ролик."""
    st = load_state()
    res = api("getUpdates", offset=st["offset"], timeout=0,
              allowed_updates=["message", "callback_query"])
    process(st, res.get("result", []))
    # подтверждаем Telegram, что всё забрали: даже если состояние не сохранится
    # (сбой коммита в Actions), те же сообщения не придут второй раз
    api("getUpdates", offset=st["offset"], timeout=0, limit=1)
    maybe_autobuild(st)
    save_state(st)


def poll_loop():
    print("[TAMRA] Бот Tamra School слушает Telegram…")
    st = load_state()
    while True:
        try:
            res = api("getUpdates", offset=st["offset"], timeout=25,
                      allowed_updates=["message", "callback_query"])
            process(st, res.get("result", []))
            maybe_autobuild(st)
            save_state(st)
        except Exception as e:
            print(f"[TAMRA] Ошибка опроса (не критично): {e}")
            time.sleep(5)


if __name__ == "__main__":
    if not TOKEN:
        sys.exit("Нет TAMRA_TG_TOKEN — создай бота в @BotFather и положи токен в окружение.")
    if "--once" in sys.argv:
        poll_once()
    else:
        poll_loop()
