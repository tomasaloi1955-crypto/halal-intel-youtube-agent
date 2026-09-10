# telegram_channel_poster.py — ежедневный разбор в Telegram-канал «Халяль Интеллидженс».
#
# ЗАЧЕМ. Каждый Shorts/пост зовёт «полный разбор в Telegram», но раньше в канал
# ничего не постилось — воронка вела в пустоту. Теперь агент кладёт сюда разбор
# глубже и полезнее, чем в Shorts: 700-1200 знаков, структура, вопрос дня для
# обсуждения. Это сердце воронки между площадками (см. docs/CONTENT_STRATEGY.md).
#
# ВКЛЮЧЕНИЕ. Нужны:
#   - бот-администратор канала. По умолчанию берётся TELEGRAM_BOT_TOKEN; если постить
#     должен другой бот (напр. общий алертер «halalai», который уже админ канала) —
#     задай его токен в секрете TELEGRAM_CHANNEL_BOT_TOKEN.
#   - канал: TELEGRAM_CHANNEL_ID (по умолчанию @halal_intelligence, можно переопределить
#     секретом — @юзернейм или числовой id).
# Нет бота-админа в канале — публикация не пройдёт, придёт понятный алерт (не роняет цикл).
import os

import requests

from threads_poster import _chat, _env, _tg_alert

CHANNEL_LINK = "https://t.me/halal_intelligence"
BRAND_HANDLE = "@Freya2013"
DEFAULT_CHANNEL = "@halal_intelligence"

_SYS = (
    "Ты ведущий Telegram-канала «Халяль Интеллидженс» — «ИИ и деньги, по совести». "
    "Пишешь для предпринимателей-мусульман из СНГ и мира, 25-45 лет. Тон спокойный, "
    "уверенный, тёплый, без религиозного назидания и без запугивания."
)


def _prompt(content, video_url):
    title = content.get("title_shorts") or content.get("title_long") or ""
    desc = (content.get("description") or "")[:700]
    script = (content.get("shorts_script") or content.get("long_script") or "")[:1200]
    vid = f"\nСсылка на короткое видео по теме: {video_url}" if video_url else ""
    return (
        "Напиши пост для Telegram-канала на русском по этому материалу дня. "
        "НЕ копия сценария видео, а самостоятельный разбор — глубже и полезнее, чем в Shorts.\n\n"
        "Структура (без служебных заголовков в тексте):\n"
        "1) Первая строка — цепляющая, но без кликбейта и стоп-слов (не «шок», «опасность», «уволит»).\n"
        "2) 2-3 коротких абзаца: что произошло / как это работает простыми словами, с конкретикой.\n"
        "3) Отдельный абзац «По совести:» — честная оценка для мусульманина-предпринимателя: "
        "кому реально полезно, где грань честности к клиенту, нет ли скрытого вреда.\n"
        "4) «Вопрос дня:» — один конкретный вопрос, на который подписчику легко ответить в комментариях.\n"
        f"5) Последняя строка: «Внедрение ИИ в бизнес — {BRAND_HANDLE}».\n\n"
        "700-1200 знаков. Без markdown-звёздочек. Абзацы через пустую строку. "
        "Вывод — только готовый текст поста.\n\n"
        f"Заголовок: {title}\n\nОписание: {desc}\n\nСценарий (источник фактов): {script}{vid}"
    )


def post_once(content=None, video_id=None):
    """Публикует дневной разбор в Telegram-канал. Никогда не роняет автопилот."""
    channel = _env("TELEGRAM_CHANNEL_ID", DEFAULT_CHANNEL)
    token = _env("TELEGRAM_CHANNEL_BOT_TOKEN") or _env("TELEGRAM_BOT_TOKEN")
    enabled = _env("TELEGRAM_CHANNEL_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    if not enabled or not channel or not token:
        print("[TG-КАНАЛ] Пропуск — нет канала или токена бота (или выключено).")
        return None
    if not content:
        print("[TG-КАНАЛ] Пропуск — нет контента дня.")
        return None

    # Дешёвая проверка ДО генерации: видит ли бот канал и админ ли он. Пока нет —
    # не тратим вызов ИИ и не шлём алерт (это состояние настройки, не сбой).
    try:
        chk = requests.get(f"https://api.telegram.org/bot{token}/getChat",
                           params={"chat_id": channel}, timeout=30).json()
        if not chk.get("ok"):
            print(f"[TG-КАНАЛ] Канал ещё не подключён: {chk.get('description', '')[:160]} "
                  f"(добавь бота админом в {channel} или задай TELEGRAM_CHANNEL_BOT_TOKEN)")
            return None
    except requests.RequestException as e:
        print(f"[TG-КАНАЛ] getChat не ответил ({e}) — пропускаю на этот раз.")
        return None

    video_url = f"https://youtube.com/shorts/{video_id}" if video_id else None
    try:
        text = _chat(_SYS, _prompt(content, video_url))[:3900]
    except Exception as e:
        print(f"[TG-КАНАЛ] Ошибка генерации: {e}")
        _tg_alert(f"СБОЙ разбора для Telegram-канала: {str(e)[:200]}")
        return None

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": channel, "text": text, "disable_web_page_preview": "false"},
            timeout=60,
        )
        r.raise_for_status()
        print("[TG-КАНАЛ] Разбор опубликован ✅")
        return text
    except requests.RequestException as e:
        detail = (getattr(getattr(e, "response", None), "text", "") or str(e)).lower()
        # «канал ещё не подключён» (бот не админ / не тот id) — это состояние настройки,
        # а не сбой: печатаем и молчим, чтобы не спамить алертами каждый день.
        not_setup = any(s in detail for s in (
            "chat not found", "bot is not a member", "not enough rights",
            "need administrator", "chat_admin_required", "have no rights",
        ))
        if not_setup:
            print(f"[TG-КАНАЛ] Канал ещё не подключён (бот не админ/не тот id): {detail[:160]}")
            return None
        print(f"[TG-КАНАЛ] Ошибка публикации: {detail[:200]}")
        _tg_alert(f"СБОЙ Telegram-канала: не смог опубликовать разбор.\n{detail[:200]}")
        return None


if __name__ == "__main__":
    post_once()
