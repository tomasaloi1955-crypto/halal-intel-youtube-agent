# content_schedule.py
from datetime import datetime
from topic_researcher import get_next_topic, prefetch_topics

# Пн=0 Вт=1 Ср=2 Чт=3 Пт=4 Сб=5 Вс=6
SCHEDULE = {
    0: "digest",       # Понедельник
    1: "digest",       # Вторник
    2: "automation",   # Среда
    3: "digest",       # Четверг
    4: "digest",       # Пятница
    5: "automation",   # Суббота
    6: "digest",       # Воскресенье
}

BRAND_HANDLE = "@Freya2013"
CHANNEL_LINK = "https://t.me/halal_intelligence"


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


def get_schedule_info():
    today = datetime.now()
    weekday = today.weekday()
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    content = SCHEDULE[weekday]
    return {
        "day": day_names[weekday],
        "content_type": content,
        "label": "Дайджест новостей" if content == "digest" else "Урок по автоматизации",
    }


if __name__ == "__main__":
    info = get_schedule_info()
    print(f"Сегодня ({info['day']}): {info['label']}")
    if info["content_type"] == "automation":
        topic = get_automation_topic()
        print(f"Тема: {topic['title']}")
        print(f"Инструмент: {topic.get('tool', '')}")
        print(f"Регион: {topic.get('region', 'Мир')}")
