# negotiator.py — ИИ-переговорщик на Freelancer.com: сам откликается на подходящие
# заказы, ведёт переписку с заказчиком от имени владелицы и сообщает в Telegram
# ТОЛЬКО когда сделка заключена (заказчик выбрал нас и мы приняли заказ).
#
# Только Freelancer: у него официальный API для откликов и сообщений, бана за это нет.
# FL.ru и Reddit сюда не входят — там автоматизация переписки = риск бана.
#
# Цены, услуги и правила (в т.ч. шариат) — в negotiator_profile.md.
#
# Переменные окружения:
#   FREELANCER_OAUTH_TOKEN — личный токен Freelancer (developers.freelancer.com)
#   ANTHROPIC_API_KEY      — ключ Claude (console.anthropic.com): переписка и сводка сделки
#   NEGOTIATOR_GEMINI_API_KEY — бесплатный Gemini: отбор заказов и текст отклика.
#                            Лучше ключ из отдельного проекта Google, чтобы не делить
#                            квоту (20 запросов/сутки на модель) с YouTube-автопилотом;
#                            если не задан — берётся GEMINI_API_KEY.
#   TELEGRAM_BOT_TOKEN, TELEGRAM_ALERT_CHAT_ID — куда слать новость о сделке
#   NEGOTIATOR_DRY_RUN=1   — ничего не отправлять на Freelancer, только показать
#                            в Telegram, что агент написал бы (режим проверки)
#   NEGOTIATOR_MAX_BIDS_PER_DAY, NEGOTIATOR_MAX_EVALS_PER_DAY — дневные лимиты
#   NEGOTIATOR_STARTER_MIN_USD — нижняя граница ставки, пока нет отзывов (0 = выключить)
import json
import os
import time
from datetime import date

import anthropic
import google.generativeai as genai
import requests

from lead_finder import fetch_freelancer, is_relevant, HEADERS
from paths import dpath
from telegram_notify import notify, alert_fail

API = "https://www.freelancer.com/api"
MODEL = os.getenv("NEGOTIATOR_MODEL", "claude-opus-5")
# Экономия: заказы публичные, их отбирает бесплатный Gemini. Claude тратим только на
# переписку с заказчиком — её мало, и туда не отдаём чужие сообщения в бесплатный
# Gemini (Google учится на запросах бесплатного тарифа).
# Своя модель: квота считается на модель, 2.5-flash занята автопилотом, 3.6-flash — генератором примеров.
GEMINI_MODEL = os.getenv("NEGOTIATOR_GEMINI_MODEL", "gemini-3.5-flash")
DRY_RUN = os.getenv("NEGOTIATOR_DRY_RUN", "").lower() in ("1", "true", "yes", "on")
# Бесплатный аккаунт Freelancer даёт мало откликов в месяц — тратим их на лучшие заказы.
MAX_BIDS_PER_DAY = int(os.getenv("NEGOTIATOR_MAX_BIDS_PER_DAY", "3"))
# Бесплатный Gemini даёт 20 запросов/сутки на модель — оставляем запас.
MAX_EVALS_PER_DAY = int(os.getenv("NEGOTIATOR_MAX_EVALS_PER_DAY", "15"))
# ...и около 10 запросов в минуту: 22.09.2026 первый запуск упёрся в минутный лимит на 11-м заказе.
GEMINI_PAUSE_SEC = 8
MIN_AMOUNT_USD = 20  # абсолютный минимум из negotiator_profile.md (24.09.2026 снижен со $100 ради первых отзывов)
# Стартовый режим: пока на Freelancer нет отзывов, заказчики почти не выбирают новичков
# по полной цене — за 22–24.09.2026 из-за вилки бюджета пропущено 5 подходящих заказов
# при одном отправленном отклике. Если вилка заказчика ниже нашего минимума, но не ниже
# этой суммы — откликаемся по верхней границе вилки и дальше не уступаем.
# После первых 3–5 отзывов выставить NEGOTIATOR_STARTER_MIN_USD=0 (выключить).
STARTER_MIN_USD = float(os.getenv("NEGOTIATOR_STARTER_MIN_USD", "20"))

STATE_FILE = dpath("negotiator_state.json")
PROFILE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "negotiator_profile.md")

TOKEN = os.getenv("FREELANCER_OAUTH_TOKEN", "").strip()
client = anthropic.Anthropic()


# ---------- Freelancer API ----------

def fl(method, path, **kwargs):
    headers = {**HEADERS, "Freelancer-OAuth-V1": TOKEN}
    resp = requests.request(method, f"{API}/{path}", headers=headers, timeout=30, **kwargs)
    if not resp.ok:
        raise RuntimeError(f"Freelancer {method} {path}: {resp.status_code} {resp.text[:300]}")
    return resp.json()["result"]


def my_user_id():
    return fl("GET", "users/0.1/self/")["id"]


# ---------- Claude ----------

def load_profile():
    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        return f.read()


SYSTEM_BASE = (
    "You are the negotiation assistant of a freelance developer who sells AI automations "
    "on Freelancer.com. You write bids and chat replies on her behalf, in first person as "
    "the freelancer. Your goal is to close deals that she can actually deliver, on terms "
    "that follow every rule in her profile below — including the Islamic (sharia) rules, "
    "which are never negotiable, even to win a deal. The profile is written in Russian; "
    "write to clients in their language (usually English). Never invent experience, "
    "reviews, links or facts that are not in the profile.\n\n"
    "=== PROFILE ===\n"
)


def ask_claude(task, schema, effort):
    """Один запрос к Claude со строгим JSON-ответом. Профиль кэшируется между запросами."""
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-06-01"],
        fallbacks=[{"model": "claude-opus-4-8"}],
        system=[{
            "type": "text",
            "text": SYSTEM_BASE + load_profile(),
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": task}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude отказался отвечать")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


class GeminiQuotaExhausted(Exception):
    """429 от Gemini. daily=True — кончилась суточная квота, иначе минутная."""
    def __init__(self, message, daily):
        super().__init__(message)
        self.daily = daily


def ask_gemini(task, schema):
    """Отбор заказа бесплатным Gemini. JSON проверяем сами по полям схемы."""
    genai.configure(api_key=os.getenv("NEGOTIATOR_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY"))
    fields = ", ".join(f"{k} ({v['type']})" for k, v in schema["properties"].items())
    prompt = (SYSTEM_BASE + load_profile() + "\n=== TASK ===\n" + task +
              f"\n\nAnswer with one JSON object with exactly these keys: {fields}.")
    try:
        text = genai.GenerativeModel(GEMINI_MODEL).generate_content(
            prompt, generation_config={"response_mime_type": "application/json"},
        ).text
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            # Google называет квоту в тексте ошибки: ...PerDay... или ...PerMinute...
            raise GeminiQuotaExhausted(str(e)[:200], daily="PerDay" in str(e))
        raise
    data = json.loads(text)
    missing = [k for k in schema["required"] if k not in data]
    if missing:
        raise ValueError(f"Gemini не вернул поля {missing}")
    return data


BID_SCHEMA = {
    "type": "object",
    "properties": {
        "bid": {"type": "boolean"},
        "reason_ru": {"type": "string"},
        "amount_usd": {"type": "number"},
        "floor_usd": {"type": "number"},
        "period_days": {"type": "integer"},
        "proposal": {"type": "string"},
    },
    "required": ["bid", "reason_ru", "amount_usd", "floor_usd", "period_days", "proposal"],
    "additionalProperties": False,
}

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        # reply — ответить заказчику; escalate — нужен человек (звонок, спорные
        # условия, подозрение на мошенничество); wait — отвечать нечего.
        "action": {"type": "string", "enum": ["reply", "escalate", "wait"]},
        "message": {"type": "string"},
        "note_ru": {"type": "string"},
    },
    "required": ["action", "message", "note_ru"],
    "additionalProperties": False,
}

DEAL_SCHEMA = {
    "type": "object",
    "properties": {"summary_ru": {"type": "string"}},
    "required": ["summary_ru"],
    "additionalProperties": False,
}


# ---------- Состояние ----------

def load_state():
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
    state.setdefault("projects", {})   # project_id -> что мы о нём знаем и что сделали
    state.setdefault("threads", {})    # thread_id -> id последнего обработанного сообщения
    # Заказы, пропущенные из-за бюджета при прежнем минимуме, оцениваем заново.
    if STARTER_MIN_USD:
        for pid in [pid for pid, e in state["projects"].items()
                    if "bid_id" not in e and "бюджет заказчика ниже" in str(e.get("decision", ""))]:
            del state["projects"][pid]
    today = date.today().isoformat()
    if state.get("day", {}).get("date") != today:
        state["day"] = {"date": today, "bids": 0, "evals": 0}
    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------- 1. Новые отклики ----------

def to_usd(amount, project):
    return amount * float((project.get("currency") or {}).get("exchange_rate") or 1)


def from_usd(amount_usd, project):
    return amount_usd / float((project.get("currency") or {}).get("exchange_rate") or 1)


def submit_bid(pid, entry, me):
    """Отправляет отклик на Freelancer. False — площадка не приняла."""
    try:
        bid = fl("POST", "projects/0.1/bids/", json={
            "project_id": int(pid), "bidder_id": me, "amount": entry["amount"],
            "period": entry["period"], "milestone_percentage": 100,
            "description": entry["proposal"],
        })
    except Exception as e:
        # Частая причина — в профиле нет навыков, которых требует заказ,
        # или заказ уже закрыт.
        entry["bid_error"] = str(e)[:300]
        print(f"[negotiator] Отклик на {pid} не прошёл — {e}")
        return False
    entry["bid_id"] = bid["id"]
    print(f"[negotiator] Отклик на {pid}: {entry['amount']} {entry['currency']}")
    return True


def send_drafts(state, me):
    """Отклики, показанные в режиме проверки, отправляем после его выключения."""
    if DRY_RUN:
        return
    for pid, entry in state["projects"].items():
        if "proposal" in entry and "bid_id" not in entry and "bid_error" not in entry:
            if submit_bid(pid, entry, me):
                state["day"]["bids"] += 1


def place_bids(state, me):
    try:
        leads = fetch_freelancer()
    except Exception as e:
        print(f"[negotiator] Freelancer: не удалось получить заказы — {e}")
        return
    fresh = {}
    for lead in leads:
        p = lead["raw"]
        pid = str(p["id"])
        # Почасовые заказы не берём: у владелицы фиксированный прайс за проект.
        if pid in state["projects"] or pid in fresh or p.get("type") == "hourly":
            continue
        if is_relevant(lead):
            fresh[pid] = lead
    # Мусульманская ниша — первой.
    queue = sorted(fresh.values(), key=lambda l: not l["halal"])
    print(f"[negotiator] Новых подходящих заказов: {len(queue)}")

    for lead in queue:
        day = state["day"]
        if day["bids"] >= MAX_BIDS_PER_DAY or day["evals"] >= MAX_EVALS_PER_DAY:
            print("[negotiator] Дневной лимит откликов/оценок исчерпан.")
            break
        p = lead["raw"]
        pid = str(p["id"])
        budget = p.get("budget") or {}
        code = (p.get("currency") or {}).get("code", "USD")
        task = (
            "A new project was posted. Decide whether to bid. Bid only if the job is fully "
            "covered by the services in the profile and allowed by all its rules. If you bid: "
            "amount_usd = the profile's first price for this job (sum the rows if it combines "
            "services); floor_usd = the matching minimum (−20%); period_days = the profile's "
            "delivery time for this job, never shorter; then write the proposal text.\n\n"
            f"Title: {p['title']}\n"
            f"Client budget: {budget.get('minimum')}–{budget.get('maximum')} {code} "
            f"(≈ {lead['budget']})\n"
            f"Description:\n{lead['snippet']}"
        )
        day["evals"] += 1
        try:
            decision = ask_gemini(task, BID_SCHEMA)
        except GeminiQuotaExhausted as e:
            # Заказы не помечаем просмотренными — оценим при следующем запуске.
            day["evals"] -= 1
            if e.daily:
                print(f"[negotiator] Gemini: суточный лимит исчерпан — {e}")
                day["evals"] = MAX_EVALS_PER_DAY
            else:
                print(f"[negotiator] Gemini: минутный лимит, продолжу в следующий запуск — {e}")
            break
        except Exception as e:
            print(f"[negotiator] Gemini: ошибка при оценке {pid} — {e}")
            continue
        time.sleep(GEMINI_PAUSE_SEC)
        entry = {
            "title": p["title"], "url": lead["url"], "description": lead["snippet"][:4000],
            "currency": code, "decision": decision["reason_ru"],
        }
        state["projects"][pid] = entry
        if not decision["bid"]:
            print(f"[negotiator] Пропуск {pid}: {decision['reason_ru']}")
            continue

        amount_usd = max(decision["amount_usd"], MIN_AMOUNT_USD)
        amount = from_usd(amount_usd, p)
        # Freelancer не принимает ставку вне вилки бюджета заказчика.
        if budget.get("minimum"):
            amount = max(amount, budget["minimum"])
        if budget.get("maximum"):
            amount = min(amount, budget["maximum"])
        # Вилка заказчика может быть ниже нашей цены: уступаем не больше 20% (до floor_usd),
        # а в стартовом режиме — до STARTER_MIN_USD.
        floor_usd = max(decision["floor_usd"], MIN_AMOUNT_USD)
        if STARTER_MIN_USD:
            floor_usd = min(floor_usd, max(STARTER_MIN_USD, MIN_AMOUNT_USD))
        if to_usd(amount, p) < floor_usd - 0.5:
            entry["decision"] += (f" | бюджет заказчика ниже минимума (${floor_usd:.0f})"
                                  " — не откликаемся")
            continue
        amount = round(amount)
        # Ставка уже ниже обычного минимума — в торге дальше не уступаем.
        floor_usd = min(decision["floor_usd"], to_usd(amount, p))
        entry.update(amount=amount, floor_usd=round(floor_usd),
                     period=decision["period_days"], proposal=decision["proposal"])

        if DRY_RUN:
            notify(f"🧪 [проверка] Откликнулся бы на: {p['title']}\n{lead['url']}\n"
                   f"Ставка: {amount} {code}, срок {decision['period_days']} дн.\n"
                   f"Почему: {decision['reason_ru']}\n\n{decision['proposal']}")
        elif not submit_bid(pid, entry, me):
            continue
        day["bids"] += 1
        print(f"[negotiator] Отклик на {pid}: {amount} {code}")
        time.sleep(2)


# ---------- 2. Переписка ----------

def reply_to_messages(state, me):
    threads = fl("GET", "messages/0.1/threads/", params={"limit": 30}).get("threads", [])
    for t in threads:
        info = t.get("thread") or {}
        context = info.get("context") or {}
        pid = str(context.get("id"))
        # Отвечаем только в переписках по заказам, на которые откликнулся сам агент.
        # Остальные чаты (старые клиенты, поддержка) не трогаем.
        project = state["projects"].get(pid)
        if context.get("type") != "project" or not project or "bid_id" not in project:
            continue
        tid = str(t["id"])
        msgs = fl("GET", "messages/0.1/messages/",
                  params={"threads[]": t["id"], "limit": 50}).get("messages", [])
        msgs.sort(key=lambda m: m.get("time_created", 0))
        last_done = state["threads"].get(tid, 0)
        new_from_client = [m for m in msgs if m["id"] > last_done and m.get("from_user") != me]
        if not new_from_client:
            continue

        history = "\n".join(
            f"{'ME' if m.get('from_user') == me else 'CLIENT'}: {m.get('message', '')}" for m in msgs
        )
        task = (
            "Continue the negotiation with this client. Reply to the client's latest messages. "
            "Aim to get the project awarded to us on terms allowed by the profile. If the client "
            "insists on a call, wants terms that break the profile's rules and cannot be talked "
            "out of them, or looks like a scam — choose escalate (message = your suggested reply, "
            "note_ru = what the owner must decide). Choose wait only if nothing needs an answer.\n\n"
            f"Project: {project['title']}\nDescription:\n{project['description']}\n\n"
            f"Our bid: {project.get('amount')} {project['currency']}, "
            f"{project.get('period')} days. Lowest price we may agree to: "
            f"{project.get('floor_usd')} USD. Never agree to a shorter deadline than our bid.\n"
            f"Our proposal:\n{project.get('proposal', '')}\n\n"
            f"Conversation (oldest first):\n{history}"
        )
        try:
            answer = ask_claude(task, REPLY_SCHEMA, effort="medium")
        except Exception as e:
            print(f"[negotiator] Claude: ошибка в переписке {tid} — {e}")
            continue

        if answer["action"] == "escalate":
            notify(f"✋ Нужно твоё решение по заказу: {project['title']}\n{project['url']}\n\n"
                   f"{answer['note_ru']}\n\nЧерновик ответа:\n{answer['message']}")
        elif answer["action"] == "reply":
            if DRY_RUN:
                notify(f"🧪 [проверка] Ответил бы заказчику ({project['title']}):\n\n"
                       f"{answer['message']}")
            else:
                fl("POST", f"messages/0.1/threads/{t['id']}/messages/",
                   data={"message": answer["message"]})
        state["threads"][tid] = max(m["id"] for m in msgs)
        print(f"[negotiator] Переписка {tid}: {answer['action']}")


# ---------- 3. Сделки ----------

def check_deals(state, me):
    """Заказчик выбрал нас → принимаем заказ → сообщаем владелице."""
    pending = {str(p["bid_id"]): (pid, p) for pid, p in state["projects"].items()
               if "bid_id" in p and not p.get("deal_notified")}
    if not pending:
        return
    bids = fl("GET", "projects/0.1/bids/", params={"bids[]": list(pending)}).get("bids", [])
    for bid in bids:
        pid, project = pending[str(bid["id"])]
        status = bid.get("award_status")
        if status not in ("pending", "awarded"):
            continue
        # pending = заказчик предложил заказ и ждёт нашего согласия.
        if status == "pending" and not DRY_RUN:
            fl("PUT", f"projects/0.1/bids/{bid['id']}/", params={"action": "accept"})

        msgs = []
        try:
            threads = fl("GET", "messages/0.1/threads/", params={"limit": 30}).get("threads", [])
            thread = next((t for t in threads
                           if str((t.get("thread") or {}).get("context", {}).get("id")) == pid), None)
            if thread:
                msgs = fl("GET", "messages/0.1/messages/",
                          params={"threads[]": thread["id"], "limit": 100}).get("messages", [])
                msgs.sort(key=lambda m: m.get("time_created", 0))
        except Exception as e:
            print(f"[negotiator] Не удалось прочитать переписку по сделке {pid} — {e}")
        history = "\n".join(
            f"{'ME' if m.get('from_user') == me else 'CLIENT'}: {m.get('message', '')}" for m in msgs
        ) or "(переписки не было — заказчик выбрал нас сразу по отклику)"
        try:
            summary = ask_claude(
                "The client awarded us this project. Write the owner a brief in Russian: what "
                "exactly must be built (scope), what is NOT included, agreed price and deadline, "
                "anything we promised the client, open questions. Be concrete.\n\n"
                f"Project: {project['title']}\nDescription:\n{project['description']}\n\n"
                f"Our bid: {bid.get('amount')} {project['currency']}, {bid.get('period')} days.\n"
                f"Proposal:\n{project.get('proposal', '')}\n\nConversation:\n{history}",
                DEAL_SCHEMA, effort="medium",
            )["summary_ru"]
        except Exception as e:
            summary = f"(не удалось составить сводку: {e})"
        prefix = "🧪 [проверка] Сделка была бы принята" if DRY_RUN else "🎉 СДЕЛКА ЗАКЛЮЧЕНА"
        notify(f"{prefix}: {project['title']}\n{project['url']}\n"
               f"💰 {bid.get('amount')} {project['currency']}, срок {bid.get('period')} дн.\n\n"
               f"{summary}\n\n"
               "Начинай работу, когда заказчик создаст milestone (оплату) на Freelancer.")
        project["deal_notified"] = True


def run():
    if not TOKEN:
        print("[negotiator] FREELANCER_OAUTH_TOKEN не задан — агент выключен.")
        return
    state = load_state()
    try:
        me = my_user_id()
    except Exception as e:
        alert_fail("negotiator", f"Freelancer не пускает по токену: {e}")
        raise
    errors = []
    # Сначала сделки и переписка (тут ждёт живой заказчик), потом новые отклики.
    for step in (check_deals, reply_to_messages, send_drafts, place_bids):
        try:
            step(state, me)
        except Exception as e:
            print(f"[negotiator] {step.__name__}: {e}")
            errors.append(f"{step.__name__}: {e}")
        save_state(state)
    if errors:
        alert_fail("negotiator", "; ".join(errors)[:1000])


if __name__ == "__main__":
    run()
