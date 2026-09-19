# example_generator.py — «крючок» для продажи автопостинга. По ссылке на открытый
# Telegram-канал читает последние посты, пишет 3 новых поста в стиле этого канала и
# готовое первое сообщение владельцу. Результат сохраняется в output/examples/ и
# приходит в Telegram — остаётся переслать владельцу канала.
#
#   python example_generator.py t.me/имя_канала
#   или двойной клик по make_example.cmd — он сам спросит ссылку.
import html
import os
import re
import sys
from datetime import datetime, timezone

import requests

from ai_processor import _call_gemini, CHANNEL_LINK
from telegram_notify import notify

OUT_DIR = os.path.join("output", "examples")
MAX_POSTS_FOR_STYLE = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def channel_name(link):
    """t.me/name, https://t.me/s/name/123, @name → name."""
    link = link.strip()
    m = re.search(r"(?:t\.me/(?:s/)?|@)([A-Za-z0-9_]{4,})", link)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_]{4,}", link):
        return link
    raise ValueError(f"Не похоже на ссылку на Telegram-канал: {link!r}")


def _meta(page, prop):
    m = re.search(rf'<meta property="{prop}" content="([^"]*)"', page)
    return html.unescape(m.group(1)) if m else ""


def fetch_channel(name):
    """Открытая веб-версия канала t.me/s/… — без входа в аккаунт, последние ~20 постов."""
    resp = requests.get(f"https://t.me/s/{name}", headers=HEADERS, timeout=20)
    resp.raise_for_status()
    page = resp.text
    if "tgme_channel_info" not in page:
        raise ValueError(
            f"Канал @{name} не найден или закрыт — генератор работает только с открытыми каналами"
        )
    posts = []
    for raw in re.findall(
        r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', page, re.S
    ):
        text = re.sub(r"<br\s*/?>", "\n", raw)
        text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
        if len(text) > 40:
            posts.append(text)
    dates = [
        datetime.fromisoformat(d)
        for d in re.findall(r'<time datetime="([^"]+)"', page)
    ]
    return {
        "name": name,
        "title": _meta(page, "og:title"),
        "description": _meta(page, "og:description"),
        "posts": posts[-MAX_POSTS_FOR_STYLE:],
        "dates": dates,
    }


def activity(dates):
    """Как давно был последний пост и как часто канал выходит — аргумент для владельца."""
    if not dates:
        return None, None
    now = datetime.now(timezone.utc)
    days_silent = (now - max(dates)).days
    span_days = max((max(dates) - min(dates)).days, 1)
    per_week = round(len(dates) / span_days * 7, 1)
    return days_silent, per_week


PROMPT = """Ты помогаешь фрилансеру продать услугу «автопостинг в Telegram»: посты выходят
каждый день сами, владелец только утверждает темы. Чтобы зацепить владельца канала,
нужно показать, как его канал мог бы выглядеть, а не рассказывать про технологии.

Канал: «{title}» (@{name})
Описание канала: {description}
Активность: {activity}

Последние посты канала (от старых к новым):
{posts}

Задача:
1. Коротко определи стиль канала: тема, тон, длина постов, эмодзи, структура, призыв в конце.
2. Напиши 3 НОВЫХ поста для этого канала, неотличимых по стилю от его постов (та же длина,
   та же подача, те же приёмы оформления). Темы — свежие, не повторяющие последние посты,
   полезные его аудитории. Если канал продаёт товар/услугу — хотя бы один пост продающий.
   Не выдумывай конкретные цены, адреса, акции, отзывы и факты о бизнесе, которых нет в постах.
3. Напиши первое сообщение владельцу канала от лица девушки-фрилансера. Коротко (4–6
   предложений), по-человечески, без канцелярита и без слов «ИИ», «нейросеть», «автоматизация»
   в первой фразе. Начни с «Ас-саляму алейкум!», если канал мусульманский, иначе с «Здравствуйте!».
   Сделай конкретное наблюдение о его канале (если давно не было постов — мягко упомяни это),
   скажи, что сделала 3 примера постов в его стиле, и предложи прислать. Контакт не добавляй.

Аяты и хадисы: цитируй только общеизвестные, с точным источником (сура:аят, сборник).
Если не уверена в точности формулировки или источника — не цитируй, пиши своими словами.

Жёсткие правила: никакого харама (алкоголь, азарт, риба, свинина, откровенный контент),
никаких изображений людей не предлагать. Пиши на языке канала.

Ответ — строго JSON без пояснений:
{{"style": "2–3 предложения о стиле",
  "posts": ["пост 1", "пост 2", "пост 3"],
  "pitch": "сообщение владельцу"}}"""


def generate(channel):
    days_silent, per_week = activity(channel["dates"])
    if days_silent is None:
        activity_text = "неизвестно"
    else:
        activity_text = (
            f"последний пост {days_silent} дн. назад, в среднем {per_week} постов в неделю"
        )
    posts = "\n\n---\n\n".join(p[:1500] for p in channel["posts"])
    result = _call_gemini(PROMPT.format(
        title=channel["title"], name=channel["name"],
        description=channel["description"] or "нет", activity=activity_text, posts=posts,
    ))
    if not result or len(result.get("posts") or []) < 3 or not result.get("pitch"):
        raise RuntimeError("ИИ не вернул примеры — попробуй ещё раз позже (возможно, кончилась дневная квота)")
    result["activity"] = activity_text
    return result


RELIGIOUS_QUOTE_RE = re.compile(
    r"сур[аы]|аят|хадис|пророк|аль-бухари|муслим\b|ат-тирмизи|абу дауд", re.I
)


def quote_warning(result):
    if any(RELIGIOUS_QUOTE_RE.search(p) for p in result["posts"]):
        return ("⚠️ В примерах есть аяты или хадисы — ИИ может ошибиться в источнике. "
                "Сверь цитаты перед отправкой владельцу.")
    return ""


def render(channel, result):
    lines = [
        f"# Примеры для @{channel['name']} — {channel['title']}",
        f"https://t.me/{channel['name']}",
        f"Активность: {result['activity']}",
        f"Стиль: {result['style']}",
        quote_warning(result),
        "",
        "## Сообщение владельцу",
        result["pitch"],
        "",
    ]
    for i, post in enumerate(result["posts"], 1):
        lines += [f"## Пример {i}", post, ""]
    lines += [
        "---",
        f"Когда владелец ответит «присылайте» — отправь примеры и ссылку на свой канал "
        f"как доказательство, что автопостинг работает: {CHANNEL_LINK}",
    ]
    return "\n".join(lines)


def send_to_telegram(channel, result):
    """Отдельными сообщениями — чтобы каждое можно было переслать владельцу как есть."""
    notify(f"🎯 Примеры для @{channel['name']} ({channel['title']})\n"
           f"Активность: {result['activity']}\n\nНиже: сообщение владельцу и 3 примера.\n"
           + quote_warning(result))
    notify(result["pitch"])
    for post in result["posts"]:
        notify(post)


def main(link):
    channel = fetch_channel(channel_name(link))
    if len(channel["posts"]) < 3:
        raise ValueError(f"В канале @{channel['name']} меньше 3 текстовых постов — стиль не понять")
    result = generate(channel)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{channel['name']}.md")
    text = render(channel, result)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    send_to_telegram(channel, result)
    print(text)
    print(f"\nСохранено: {path} (и отправлено тебе в Telegram)")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else input("Ссылка на Telegram-канал: ")
    try:
        main(arg)
    except Exception as e:
        print(f"Не получилось: {e}")
        sys.exit(1)
