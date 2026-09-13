# content_schedule.py
from datetime import datetime
from topic_researcher import (get_next_topic, prefetch_topics, get_next_tool_topic,
                              prefetch_tool_topics, get_next_verdict_topic,
                              prefetch_verdict_topics)

# Пн=0 Вт=1 Ср=2 Чт=3 Пт=4 Сб=5 Вс=6
# 3x/нед — свежие новости ИИ, 2x/нед — обзоры ИИ-инструментов, 1x — автоматизация,
# 1x — фирменная рубрика «Халяль или харам?» (единственный формат, который не
# повторит ни один из тысячи одинаковых AI-каналов; тянет досмотр и комментарии).
SCHEDULE = {
    0: "digest",         # Понедельник — новости ИИ
    1: "tool_review",    # Вторник — обзор ИИ-инструмента
    2: "automation",     # Среда — автоматизация бизнеса + ТГ
    3: "digest",         # Четверг — новости ИИ
    4: "tool_review",    # Пятница — обзор ИИ-инструмента
    5: "halal_verdict",  # Суббота — «Халяль или харам?»
    6: "digest",         # Воскресенье — новости ИИ
}

LABELS = {
    "digest": "Дайджест новостей ИИ",
    "tool_review": "Обзор ИИ-инструмента",
    "automation": "Урок по автоматизации",
    "halal_verdict": "Халяль или харам?",
}

BRAND_HANDLE = "@Freya2013"
CHANNEL_LINK = "https://t.me/Halalaifreya"


def get_today_content_type():
    return SCHEDULE[datetime.now().weekday()]


def get_automation_topic():
    """Get topic for this week. Auto-researches new topics after week 16."""
    week = datetime.now().isocalendar()[1]
    topic = get_next_topic(week)

    # Prefetch next topics in background if stock is low
    # (runs fast, Gemini call is async-friendly)
    try:
        prefetch_topics(count=3)
    except Exception as e:
        print(f"[PREFETCH] Не критично: {e}")

    return topic


def get_tool_review_topic():
    """Get AI tool review topic for this week. Auto-researches new tools after base list runs out."""
    week = datetime.now().isocalendar()[1]
    topic = get_next_tool_topic(week)

    try:
        prefetch_tool_topics(count=3)
    except Exception as e:
        print(f"[PREFETCH] Не критично: {e}")

    return topic


def get_verdict_topic():
    """Тема рубрики «Халяль или харам?» на эту неделю (спорный приём применения ИИ)."""
    week = datetime.now().isocalendar()[1]
    topic = get_next_verdict_topic(week)

    try:
        prefetch_verdict_topics(count=3)
    except Exception as e:
        print(f"[PREFETCH] Не критично: {e}")

    return topic


def get_schedule_info():
    today = datetime.now()
    weekday = today.weekday()
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    content = SCHEDULE[weekday]
    return {
        "day": day_names[weekday],
        "content_type": content,
        "label": LABELS[content],
    }


if __name__ == "__main__":
    info = get_schedule_info()
    print(f"Сегодня ({info['day']}): {info['label']}")
    if info["content_type"] == "automation":
        topic = get_automation_topic()
        print(f"Тема: {topic['title']}")
        print(f"Инструмент: {topic.get('tool', '')}")
        print(f"Регион: {topic.get('region', 'Мир')}")
