# lead_bot/app.py — бот для приёма заявок в Telegram и WhatsApp.
# Клиент пишет в любой из мессенджеров → бот задаёт вопросы из config.json →
# готовая заявка приходит владельцу в Telegram (и, если задан, на LEADS_WEBHOOK_URL —
# например, в Google Таблицу через Apps Script или в CRM).
#
# Один процесс принимает вебхуки обоих мессенджеров:
#   /telegram  — Telegram Bot API (setWebhook делается сам при старте)
#   /whatsapp  — WhatsApp Cloud API от Meta (GET — проверка, POST — сообщения)
import csv
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import threading
import time

import requests
from flask import Flask, Response, abort, request

HERE = os.path.dirname(os.path.abspath(__file__))

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

WA_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WA_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WA_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
WA_API = os.getenv("WHATSAPP_API_VERSION", "v21.0")

LEADS_WEBHOOK_URL = os.getenv("LEADS_WEBHOOK_URL", "")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
DB_PATH = os.getenv("LEAD_DB", os.path.join(HERE, "leads.sqlite3"))
CONFIG_PATH = os.getenv("LEAD_CONFIG", os.path.join(HERE, "config.json"))

SESSION_TTL = 24 * 3600          # недописанная заявка забывается через сутки
RESTART_WORDS = {"/start", "start", "старт", "заново", "меню", "привет", "сәлем", "салам"}

with open(CONFIG_PATH, encoding="utf-8") as f:
    CFG = json.load(f)
QUESTIONS = CFG["questions"]

app = Flask(__name__)
_db_lock = threading.Lock()


# ── Хранилище ─────────────────────────────────────────────────────────────
def _db():
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS sessions (key TEXT PRIMARY KEY, step INTEGER,"
                " answers TEXT, updated REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS seen (msg_id TEXT PRIMARY KEY, at REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " created REAL, channel TEXT, user_id TEXT, answers TEXT)")
    return con


def _already_seen(msg_id):
    """Meta и Telegram повторяют доставку, если ответ задержался, — отвечаем один раз."""
    with _db_lock, _db() as con:
        con.execute("DELETE FROM seen WHERE at < ?", (time.time() - 3 * 24 * 3600,))
        cur = con.execute("INSERT OR IGNORE INTO seen VALUES (?, ?)", (msg_id, time.time()))
        return cur.rowcount == 0


def _load_session(key):
    with _db_lock, _db() as con:
        row = con.execute("SELECT step, answers, updated FROM sessions WHERE key = ?",
                          (key,)).fetchone()
    if not row or time.time() - row[2] > SESSION_TTL:
        return None
    return {"step": row[0], "answers": json.loads(row[1])}


def _save_session(key, session):
    with _db_lock, _db() as con:
        con.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?)",
                    (key, session["step"], json.dumps(session["answers"], ensure_ascii=False),
                     time.time()))


def _save_lead(channel, user_id, answers):
    with _db_lock, _db() as con:
        con.execute("INSERT INTO leads (created, channel, user_id, answers) VALUES (?, ?, ?, ?)",
                    (time.time(), channel, user_id, json.dumps(answers, ensure_ascii=False)))


# ── Диалог (общий для обоих мессенджеров) ─────────────────────────────────
def _fmt(text, answers=None):
    return text.replace("{business}", CFG.get("business_name", "")).replace(
        "{name}", (answers or {}).get("name", "").strip() or "")


def _question_text(q, channel):
    text = q["text"]
    if q.get("choices") and channel == "whatsapp":
        # в WhatsApp кнопок нет — нумеруем варианты, ответить можно цифрой
        text += "\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(q["choices"], 1))
    return text


def _next_step(step, channel):
    """Номер следующего вопроса. В WhatsApp телефон уже известен — его не спрашиваем."""
    while step < len(QUESTIONS):
        if channel == "whatsapp" and QUESTIONS[step].get("type") == "phone":
            step += 1
            continue
        return step
    return step


def _parse_answer(q, text):
    """Возвращает (значение, None) или (None, текст ошибки)."""
    text = text.strip()
    if q.get("choices"):
        choices = q["choices"]
        if text.isdigit() and 1 <= int(text) <= len(choices):
            return choices[int(text) - 1], None
        for c in choices:
            if c.lower() == text.lower():
                return c, None
        return None, CFG["bad_choice"]
    if q.get("type") == "phone":
        if len(re.sub(r"\D", "", text)) < 10:
            return None, CFG["bad_phone"]
    if not text:
        return None, q["text"]
    return text, None


def handle_message(channel, user_id, text, profile=None):
    """Главная логика. Возвращает список ответов: [(текст, варианты-кнопок или None)]."""
    key = f"{channel}:{user_id}"
    session = _load_session(key)
    word = text.strip().lower()

    def ask(step, answers, prefix=None):
        step = _next_step(step, channel)
        _save_session(key, {"step": step, "answers": answers})
        q = QUESTIONS[step]
        out = [(prefix, None)] if prefix else []
        return out + [(_question_text(q, channel), q.get("choices"))]

    if session is None or word in RESTART_WORDS:
        answers = {}
        if channel == "whatsapp":
            answers["phone"] = "+" + user_id
        if profile:
            answers["_profile"] = profile
        return ask(0, answers, _fmt(CFG["greeting"]))

    step, answers = session["step"], session["answers"]
    if step >= len(QUESTIONS):
        notify_owner(f"💬 Ещё сообщение от клиента ({_who(channel, user_id, answers)}):\n{text}")
        return [(CFG["already_done"], None)]

    q = QUESTIONS[step]
    value, error = _parse_answer(q, text)
    if error:
        return [(error, q.get("choices"))]
    answers[q["key"]] = value

    step = _next_step(step + 1, channel)
    if step < len(QUESTIONS):
        return ask(step, answers)

    _save_session(key, {"step": step, "answers": answers})
    _save_lead(channel, user_id, answers)
    deliver_lead(channel, user_id, answers)
    return [(_fmt(CFG["done"], answers).replace(", !", "!"), None)]


# ── Куда уходит готовая заявка ────────────────────────────────────────────
def _who(channel, user_id, answers):
    if channel == "whatsapp":
        return f"WhatsApp +{user_id}"
    handle = (answers.get("_profile") or "").strip()
    return f"Telegram {handle}" if handle else f"Telegram id {user_id}"


def notify_owner(text):
    if not (TG_TOKEN and OWNER_CHAT_ID):
        print(f"[LEAD] {text}")
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      json={"chat_id": OWNER_CHAT_ID, "text": text,
                            "disable_web_page_preview": True}, timeout=15)
    except Exception as e:
        print(f"[LEAD] владельцу не отправлено: {e}")


def deliver_lead(channel, user_id, answers):
    lines = [f"🔔 Новая заявка — {_who(channel, user_id, answers)}"]
    for q in QUESTIONS:
        if q["key"] in answers:
            lines.append(f"{q['label']}: {answers[q['key']]}")
    notify_owner("\n".join(lines))

    if LEADS_WEBHOOK_URL:
        payload = {"channel": channel, "user_id": user_id,
                   "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                   **{k: v for k, v in answers.items() if not k.startswith("_")}}
        try:
            requests.post(LEADS_WEBHOOK_URL, json=payload, timeout=15)
        except Exception as e:
            print(f"[LEAD] вебхук не ответил: {e}")


# ── Telegram ──────────────────────────────────────────────────────────────
def tg_send(chat_id, text, choices=None):
    body = {"chat_id": chat_id, "text": text}
    if choices:
        body["reply_markup"] = {"keyboard": [[{"text": c}] for c in choices],
                                "resize_keyboard": True, "one_time_keyboard": True}
    else:
        body["reply_markup"] = {"remove_keyboard": True}
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json=body, timeout=15)
    except Exception as e:
        print(f"[TG] не отправлено: {e}")


@app.post("/telegram")
def telegram_webhook():
    if TG_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != TG_SECRET:
        abort(403)
    upd = request.get_json(silent=True) or {}
    msg = upd.get("message") or {}
    chat = msg.get("chat") or {}
    if chat.get("type") != "private" or "update_id" not in upd:
        return "ok"
    if _already_seen(f"tg:{upd['update_id']}"):
        return "ok"
    # поделились контактом кнопкой — берём номер оттуда
    text = (msg.get("contact") or {}).get("phone_number") or msg.get("text") or ""
    if not text:
        return "ok"
    frm = msg.get("from") or {}
    profile = f"@{frm['username']}" if frm.get("username") else frm.get("first_name", "")
    for reply, choices in handle_message("telegram", str(chat["id"]), text, profile):
        tg_send(chat["id"], reply, choices)
    return "ok"


def tg_set_webhook():
    if not (TG_TOKEN and PUBLIC_URL):
        return
    params = {"url": f"{PUBLIC_URL}/telegram", "allowed_updates": ["message"]}
    if TG_SECRET:
        params["secret_token"] = TG_SECRET
    try:
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/setWebhook",
                          json=params, timeout=15)
        print(f"[TG] setWebhook: {r.json()}")
    except Exception as e:
        print(f"[TG] setWebhook не удался: {e}")


# ── WhatsApp Cloud API ────────────────────────────────────────────────────
def wa_send(to, text):
    try:
        r = requests.post(f"https://graph.facebook.com/{WA_API}/{WA_PHONE_ID}/messages",
                          headers={"Authorization": f"Bearer {WA_TOKEN}"},
                          json={"messaging_product": "whatsapp", "to": to,
                                "type": "text", "text": {"body": text}}, timeout=15)
        if not r.ok:
            print(f"[WA] {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"[WA] не отправлено: {e}")


@app.get("/whatsapp")
def whatsapp_verify():
    # Meta один раз проверяет адрес вебхука при подключении
    if (request.args.get("hub.mode") == "subscribe"
            and WA_VERIFY_TOKEN
            and request.args.get("hub.verify_token") == WA_VERIFY_TOKEN):
        return request.args.get("hub.challenge", "")
    abort(403)


def _wa_signature_ok():
    if not WA_APP_SECRET:
        return True
    sent = request.headers.get("X-Hub-Signature-256", "")
    good = "sha256=" + hmac.new(WA_APP_SECRET.encode(), request.get_data(),
                                hashlib.sha256).hexdigest()
    return hmac.compare_digest(sent, good)


def _wa_text(m):
    kind = m.get("type")
    if kind == "text":
        return m["text"].get("body", "")
    if kind == "button":
        return m["button"].get("text", "")
    if kind == "interactive":
        inter = m["interactive"]
        return (inter.get("button_reply") or inter.get("list_reply") or {}).get("title", "")
    return ""


@app.post("/whatsapp")
def whatsapp_webhook():
    if not _wa_signature_ok():
        abort(403)
    data = request.get_json(silent=True) or {}
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for m in value.get("messages", []):
                if _already_seen(f"wa:{m.get('id')}"):
                    continue
                text = _wa_text(m)
                if not text:
                    wa_send(m["from"], "Пока понимаю только текст — напишите, пожалуйста, словами.")
                    continue
                for reply, _ in handle_message("whatsapp", m["from"], text):
                    wa_send(m["from"], reply)
    return "ok"


# ── Служебное ─────────────────────────────────────────────────────────────
@app.get("/")
def health():
    return "lead bot ok"


@app.get("/leads.csv")
def leads_csv():
    """Выгрузка всех заявок: /leads.csv?key=ADMIN_KEY"""
    if not ADMIN_KEY or not hmac.compare_digest(request.args.get("key", ""), ADMIN_KEY):
        abort(403)
    with _db_lock, _db() as con:
        rows = con.execute("SELECT created, channel, user_id, answers FROM leads"
                           " ORDER BY id").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Дата", "Канал", "ID"] + [q["label"] for q in QUESTIONS])
    for created, channel, user_id, answers in rows:
        a = json.loads(answers)
        w.writerow([time.strftime("%Y-%m-%d %H:%M", time.localtime(created)), channel, user_id]
                   + [a.get(q["key"], "") for q in QUESTIONS])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=leads.csv"})


tg_set_webhook()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
