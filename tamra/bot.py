# bot.py — Telegram-бот Tamra School: сырые клипы + озвучка → готовый ролик «День N».
#
# Как пользоваться (всё в чате с ботом):
#   1. Присылаешь клипы и/или фото (скриншоты экрана тоже) — в том порядке, в каком они
#      должны идти в ролике.
#   2. Присылаешь озвучку: голосовое или аудиофайл. Можно добавить текстовую заметку —
#      «сегодня делала тест по математике», нейросеть учтёт её в хуке и подписи.
#   3. Бот склеивает ролик под длину озвучки, ставит плашку «ДЕНЬ N», хук, субтитры,
#      призыв в конце, делает обложку и пишет подпись с хэштегами — и присылает превью.
#   4. Кнопка «✅ В очередь» — ролик встаёт в очередь публикаций. Бот выкладывает по одному
#      ролику в день в своё время (по умолчанию 19:00 по Алматы) в YouTube, Instagram, TikTok.
#      «🔁 Другой хук» — нейросеть перепишет тексты. «❌ Удалить» — черновик в корзину.
#      Свой хук/подпись: напиши «хук: …» или «подпись: …» (относится к последнему черновику).
#
# Каждое новое голосовое — новый ролик: можно наговорить несколько дней подряд за раз,
# бот соберёт каждый отдельно и пронумерует по порядку.
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
#   TAMRA_PUBLISH_HOUR, TAMRA_TZ — час публикации и часовой пояс (по умолчанию 19 и +5, Алматы);
#                       час можно поменять и из чата: «время 20»
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
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

from paths import dpath  # noqa: E402
from tamra import montage, writer, stock, scripts, yt_auth, faces  # noqa: E402

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
    "и пришлю превью. Дальше — кнопка «В очередь»: публикую по одному ролику в день.\n"
    "Можно наговорить несколько дней сразу — каждое голосовое станет отдельным роликом.\n\n"
    "Команды:\n"
    "• готово — собрать сейчас (можно и без озвучки)\n"
    "• текст — текст озвучки для следующего дня (текст 7 — для дня 7)\n"
    "• темы — все 30 тем роликов\n"
    "• кадры — подобрать новые кадры для последнего черновика\n"
    "• очередь — что и когда выйдет\n"
    "• ютуб — подключить YouTube-канал с телефона\n"
    "• сейчас — опубликовать следующий ролик из очереди немедленно\n"
    "• убрать 5 — убрать «День 5» из очереди\n"
    "• время 20 — публиковать в 20:00\n"
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
    st.setdefault("drafts", [])
    if st.get("draft"):  # старый формат: один черновик
        st["drafts"].append(st["draft"])
    st.pop("draft", None)
    st.setdefault("pending", [])   # закрытые пачки (по одной на голосовое), ждут сборки
    st.setdefault("queue", [])     # одобренные ролики, по одному в день
    st.setdefault("history", [])
    st.setdefault("stock_used", [])
    st.setdefault("publish_hour", int(os.getenv("TAMRA_PUBLISH_HOUR", "19")))
    st.setdefault("last_publish_date", None)
    st.setdefault("last_fail_notice", None)
    used_days = [d["day"] for d in st["drafts"] + st["queue"]]
    st["day"] = max([st["day"]] + [x + 1 for x in used_days])  # номер следующего ролика
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
        out = []
        for c in spec["stock_clips"]:
            raw = stock.download(c["url"], os.path.join(srcdir, f"raw_{c['id']}.mp4"))
            path = os.path.join(srcdir, f"stock_{c['id']}.mp4")
            faces.blur_video(raw, path)  # при пересборке лица размываются так же, как при подборе
            os.remove(raw)
            out.append({"path": path, "kind": "video"})
        return out
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


def _buttons(draft_id):
    return {"inline_keyboard": [[
        {"text": "✅ В очередь", "callback_data": f"q:{draft_id}"},
        {"text": "🔁 Другой хук", "callback_data": f"redo:{draft_id}"},
        {"text": "❌ Удалить", "callback_data": f"del:{draft_id}"},
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
                  reply_markup=_buttons(draft["id"]),
                  files={"video": (os.path.basename(video), f, "video/mp4")})
    if not res.get("ok"):
        send(chat, f"Не смогла прислать видео: {res.get('description')}")
    send(chat, "Подпись (для копирования):\n\n" + writer.full_caption(t))


def _taken_stock(st):
    """Стоковые клипы, которые уже вышли или стоят в черновиках/очереди, — не повторяем."""
    ids = list(st["stock_used"])
    for d in st["drafts"] + st["queue"]:
        ids += [c["id"] for c in d.get("stock_clips", [])]
    return ids[-400:]


def build_draft(st, chat, b=None):
    """Собирает ролик из пачки b (по умолчанию — текущая). Номер дня — следующий по порядку."""
    current = b is None
    b = st["batch"] if current else b
    if not b["media"] and not b["voice"]:
        send(chat, "Пришли озвучку (и, если есть, свои клипы или фото) — потом соберу ролик.")
        return
    draft = {"id": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4],
             "day": st["day"], "media": b["media"], "voice": b["voice"], "notes": b["notes"],
             "hook_override": b.get("hook"), "caption_override": b.get("caption"),
             "stock_exclude": _taken_stock(st)}
    if current:
        st["batch"] = _empty_batch()
    st["day"] += 1
    st["drafts"].append(draft)
    what = (f"{len(draft['media'])} клип(ов)" if draft["media"]
            else "подбираю кадры по смыслу озвучки")
    send(chat, f"⏳ Собираю «День {draft['day']}»: {what}"
               f"{', с озвучкой' if draft['voice'] else ', без озвучки'}. Это 1–3 минуты…")
    try:
        _write_texts(draft)
        send_preview(chat, draft)
    except Exception as e:
        print(f"[TAMRA] Сборка не удалась: {e}")
        send(chat, f"🔴 Не получилось собрать «День {draft['day']}»: {str(e)[:300]}\n"
                   "Материалы сохранены — напиши «готово», чтобы попробовать ещё раз.")
        st["drafts"].remove(draft)
        if st["day"] == draft["day"] + 1:
            st["day"] = draft["day"]  # номер не пропадает
        st["pending"].insert(0, {**_empty_batch(), "media": draft["media"], "voice": draft["voice"],
                                 "notes": draft["notes"], "hook": draft.get("hook_override"),
                                 "caption": draft.get("caption_override"),
                                 "updated": time.time(), "auto_failed": True})  # сама не повторяю


def _find_draft(st, draft_id=None):
    """Черновик по id; без id — последний присланный."""
    if draft_id:
        return next((d for d in st["drafts"] if d["id"] == draft_id), None)
    return st["drafts"][-1] if st["drafts"] else None


def _drop_draft(st, d):
    shutil.rmtree(os.path.join(WORK, d["id"]), ignore_errors=True)
    st["drafts"] = [x for x in st["drafts"] if x["id"] != d["id"]]


# ── очередь и расписание ───────────────────────────────────────────────────

def _tz():
    return timezone(timedelta(hours=float(os.getenv("TAMRA_TZ", "5"))))


def _slot_dates(st, n):
    """Даты выхода для первых n роликов очереди: по одному в день, начиная с ближайшего слота."""
    now = datetime.now(_tz())
    first = now.date()
    if st.get("last_publish_date") == first.isoformat():
        first += timedelta(days=1)  # сегодня уже выходил ролик
    return [first + timedelta(days=i) for i in range(n)]


def _fmt_date(d):
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
    return f"{d.day} {months[d.month - 1]}"


def queue_text(st):
    if not st["queue"]:
        return "Очередь пуста. Одобри черновик кнопкой «✅ В очередь»."
    dates = _slot_dates(st, len(st["queue"]))
    lines = [f"• {_fmt_date(dt)}, {st['publish_hour']}:00 — День {d['day']}: {d['texts']['hook']}"
             for dt, d in zip(dates, st["queue"])]
    return "🗓 Очередь публикаций:\n" + "\n".join(lines)


def enqueue(st, chat, d):
    st["drafts"] = [x for x in st["drafts"] if x["id"] != d["id"]]
    st["queue"].append(d)
    st["queue"].sort(key=lambda x: x["day"])
    dt = _slot_dates(st, len(st["queue"]))[st["queue"].index(d)]
    send(chat, f"✅ «День {d['day']}» в очереди — выйдет {_fmt_date(dt)} в {st['publish_hour']}:00.\n\n"
               + queue_text(st))


def publish_item(st, chat, d):
    """Публикует ролик из очереди. True — хотя бы одна площадка приняла."""
    from tamra.publish import publish_all
    # Снимаем ролик с очереди ДО публикации: если процесс упадёт посередине,
    # следующий запуск не выложит его второй раз.
    st["queue"] = [x for x in st["queue"] if x["id"] != d["id"]]
    save_state(st)
    try:
        video, _ = render(d)
        results = publish_all(video, d["texts"], writer.full_caption(d["texts"]),
                              yt_token=yt_auth.token_json(st))
    except Exception as e:
        st["queue"].insert(0, d)
        send(chat, f"🔴 «День {d['day']}» не опубликован: {str(e)[:300]}. Остаётся в очереди.")
        return False
    if not any(v.startswith("✅") for v in results.values()):
        st["queue"].insert(0, d)
        today = datetime.now(_tz()).date().isoformat()
        if st.get("last_fail_notice") != today:  # не спамим каждые 15 минут
            st["last_fail_notice"] = today
            send(chat, f"⏸ «День {d['day']}» ждёт в очереди — ни одна площадка не приняла:\n"
                       + "\n".join(f"{k}: {v}" for k, v in results.items()))
        return False
    send(chat, f"🚀 Вышел «День {d['day']}»:\n" + "\n".join(f"{k}: {v}" for k, v in results.items()))
    st["history"] = (st["history"] + [{
        "day": d["day"], "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "hook": d["texts"]["hook"], "results": results}])[-90:]
    st["stock_used"] = (st["stock_used"] + [c["id"] for c in d.get("stock_clips", [])])[-300:]
    shutil.rmtree(os.path.join(WORK, d["id"]), ignore_errors=True)
    return True


def publish_due(st):
    """Пришло время дня и сегодня ещё ничего не выходило — публикуем следующий из очереди."""
    chat = os.getenv("TAMRA_TG_CHAT_ID", "").strip() or st.get("owner")
    now = datetime.now(_tz())
    today = now.date().isoformat()
    if (chat and st["queue"] and now.hour >= st["publish_hour"]
            and st.get("last_publish_date") != today):
        if publish_item(st, chat, st["queue"][0]):
            st["last_publish_date"] = today
            if st["queue"]:
                send(chat, queue_text(st))


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
                # новое голосовое — новый ролик: прошлую пачку закрываем и соберём отдельно
                st["pending"].append(b)
                st["batch"] = b = _empty_batch()
                send(chat, "Это уже следующий ролик — прошлый соберу отдельно.")
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
        build_all(st, chat, force=True)
        return
    if low in ("сброс", "/reset", "отмена", "/cancel"):
        st["batch"] = _empty_batch()
        st["pending"] = []
        for d in list(st["drafts"]):
            _drop_draft(st, d)
        send(chat, "Очистила присланное и черновики (очередь не трогала). Присылай новое.")
        return
    if low in ("ок", "да", "в очередь", "/queue_add"):
        d = _find_draft(st)
        if d:
            enqueue(st, chat, d)
        else:
            send(chat, "Нет черновика. Пришли озвучку — соберу ролик.")
        return
    if low in ("ютуб", "youtube", "/youtube", "ютуб подключить"):
        try:
            url = yt_auth.auth_url()
        except Exception as e:
            send(chat, f"🔴 Не получилось сделать ссылку: {str(e)[:200]}")
            return
        send(chat, "Подключаем YouTube:\n\n"
                   "1️⃣ Открой ссылку ниже на телефоне.\n"
                   "2️⃣ Выбери свой Google-аккаунт, затем канал TAMRA SCHOOL.\n"
                   "3️⃣ Если Google напишет «Приложение не проверено» — «Дополнительно» → «Перейти».\n"
                   "4️⃣ Нажми «Разрешить». Откроется страница с ошибкой «localhost» — так и должно быть.\n"
                   "5️⃣ Скопируй адрес этой страницы целиком (он начинается с http://localhost) "
                   "и пришли мне сюда.\n\n" + url)
        return
    if "localhost" in low and ("code=" in low or "error=" in low):
        if "error=" in low:
            send(chat, "Google не дал доступ (нажата «Отмена»?). Напиши «ютуб» и попробуй ещё раз.")
            return
        try:
            token, name = yt_auth.exchange(yt_auth.extract_code(text))
        except Exception as e:
            send(chat, f"🔴 Не получилось подключить: {str(e)[:250]}\n"
                       "Ссылка живёт несколько минут — напиши «ютуб» и пройди заново.")
            return
        st["yt_token_enc"] = yt_auth.encrypt(token)
        warn = "" if "tamra" in name.lower() else (
            "\n⚠️ Похоже, это не канал Tamra School. Если ошиблась — напиши «ютуб» и выбери нужный.")
        send(chat, f"✅ YouTube подключён: канал «{name}». Ролики из очереди будут выходить туда.{warn}\n\n"
                   + queue_text(st))
        return
    if low in ("кадры", "новые кадры", "/frames"):
        d = _find_draft(st)
        if not d or d.get("media"):
            send(chat, "Новые кадры подбираю только для черновика без своих клипов. "
                       "Ролик из очереди сначала верни: «убрать N».")
            return
        old = [c["id"] for c in d.pop("stock_clips", [])]
        d["stock_exclude"] = list(d.get("stock_exclude", [])) + old  # те же клипы не берём
        d.pop("rendered_hook", None)
        shutil.rmtree(os.path.join(WORK, d["id"], "src"), ignore_errors=True)
        send(chat, f"Подбираю новые кадры для «День {d['day']}»…")
        try:
            send_preview(chat, d)
        except Exception as e:
            send(chat, f"🔴 Не получилось: {str(e)[:300]}")
        return
    if low in ("темы", "/topics"):
        send(chat, "30 тем роликов:\n" + scripts.titles() + "\n\nНапиши «текст 7» — пришлю текст дня 7.")
        return
    if low in ("текст", "/text") or low.startswith(("текст ", "/text ")):
        parts = low.split()
        try:
            n = int(parts[1]) if len(parts) > 1 else st["day"]
        except ValueError:
            n = st["day"]
        send(chat, scripts.script_text(n) or f"Для дня {n} текста нет — напиши «темы».")
        return
    if low in ("очередь", "/queue"):
        send(chat, queue_text(st))
        return
    if low in ("сейчас", "/now", "опубликовать", "публикуй", "/publish"):
        if st["queue"]:
            if publish_item(st, chat, st["queue"][0]):
                st["last_publish_date"] = datetime.now(_tz()).date().isoformat()
        else:
            send(chat, "Очередь пуста — сначала одобри черновик кнопкой «✅ В очередь».")
        return
    if low.startswith(("убрать ", "/remove ")):
        try:
            n = int(low.split()[1])
            d = next(x for x in st["queue"] if x["day"] == n)
        except (ValueError, IndexError, StopIteration):
            send(chat, "В очереди нет такого дня. Напиши «очередь», чтобы посмотреть.")
            return
        st["queue"].remove(d)
        st["drafts"].append(d)
        send(chat, f"«День {n}» убрала из очереди — он снова черновик. " + queue_text(st))
        return
    if low.startswith(("время ", "/time ")):
        try:
            h = int(low.split()[1].split(":")[0])
            assert 0 <= h <= 23
            st["publish_hour"] = h
            send(chat, f"Буду публиковать в {h}:00. " + queue_text(st))
        except (ValueError, IndexError, AssertionError):
            send(chat, "Напиши так: время 19")
        return
    if low.startswith(("день ", "/day ")):
        try:
            n = max(1, int(low.split()[1]))
        except (ValueError, IndexError):
            send(chat, "Напиши так: день 12")
            return
        d = _find_draft(st)
        if d:  # меняем номер последнего черновика, следующий пойдёт за ним
            d["day"] = n
            d.pop("rendered_hook", None)
            st["day"] = n + 1
            send(chat, f"Последний черновик теперь «День {n}», следующий будет «День {n + 1}».")
        else:
            st["day"] = n
            send(chat, f"Следующий ролик будет «День {n}».")
        return
    for prefix, key, field in (("хук:", "hook", "hook_override"), ("подпись:", "caption", "caption_override")):
        if low.startswith(prefix):
            value = text[len(prefix):].strip()
            d = _find_draft(st)
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
    action, _, draft_id = (cq.get("data") or "").partition(":")
    action = {"pub": "q"}.get(action, action)  # кнопки старых превью
    d = _find_draft(st, draft_id or None)
    if not d:
        queued = any(x["id"] == draft_id for x in st["queue"])
        send(chat, "Этот ролик уже в очереди." if queued else "Этот черновик уже опубликован или удалён.")
        return
    if action == "q":
        enqueue(st, chat, d)
    elif action == "del":
        _drop_draft(st, d)
        send(chat, f"Черновик «День {d['day']}» удалён.")
    elif action == "redo":
        d.pop("hook_override", None)
        send(chat, f"Переписываю тексты «День {d['day']}»…")
        try:
            _write_texts(d)
            send_preview(chat, d)
        except Exception as e:
            send(chat, f"🔴 Не получилось: {str(e)[:300]}")


def build_all(st, chat, force=False):
    """Собирает закрытые пачки по порядку, затем текущую. force — по команде «готово»:
    и неудавшиеся раньше, и текущую без ожидания."""
    built = 0
    for b in list(st["pending"]):
        if force or not b.get("auto_failed"):
            st["pending"].remove(b)
            build_draft(st, chat, b)
            save_state(st)
            built += 1
    b = st["batch"]
    if force or (b["voice"] and not b.get("auto_failed")
                 and (b["media"] or not b.get("oversize"))
                 and time.time() - b["updated"] >= IDLE_BEFORE_BUILD):
        if b["voice"] or b["media"] or not built:
            build_draft(st, chat)  # пустая пачка — подскажет, что прислать


def maybe_autobuild(st):
    """Озвучка на месте (клипы — свои или со стока), минуту ничего не приходило — собираем."""
    chat = os.getenv("TAMRA_TG_CHAT_ID", "").strip() or st.get("owner")
    if chat:
        build_all(st, chat)


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
    publish_due(st)
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
            publish_due(st)
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
