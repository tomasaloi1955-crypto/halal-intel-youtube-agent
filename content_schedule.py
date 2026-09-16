# content_schedule.py
from datetime import datetime
from topic_researcher import (get_next_topic, prefetch_topics, get_next_tool_topic,
                              prefetch_tool_topics, get_next_verdict_topic,
                              prefetch_verdict_topics)

# Пн=0 Вт=1 Ср=2 Чт=3 Пт=4 Сб=5 Вс=6
#
# Раньше расписание было новостным (3 дня дайджестов + 2 обзора). Новости про ИИ —
# самая перегретая ниша на YouTube: их слушают и пролистывают, их не сохраняют и не
# пересматривают, повода вернуться завтра они не дают. Канал на них не рос.
#
# Теперь в основе — обучающие рубрики, где зритель уносит с собой одну готовую вещь
# (это то, на чём растёт арабский канал), а новость осталась одна в неделю и подаётся
# как вау-цифра, а не как пересказ.
SCHEDULE = {
    0: "prompt_card",    # Понедельник — «Промпт дня»
    1: "ai_trick",       # Вторник — «ИИ за 20 секунд»
    2: "prompt_card",    # Среда — «Промпт дня»
    3: "ai_trick",       # Четверг — «ИИ за 20 секунд»
    4: "prompt_card",    # Пятница — «Промпт дня»
    5: "halal_verdict",  # Суббота — «Халяль или харам?» (фирменная рубрика)
    6: "wow_news",       # Воскресенье — «Вау-новость»
}

LABELS = {
    "prompt_card": "Промпт дня",
    "ai_trick": "ИИ за 20 секунд",
    "halal_verdict": "Халяль или харам?",
    "wow_news": "Вау-новость",
    # старые типы — оставлены, чтобы не падать на записях в очереди длинных видео
    "digest": "Дайджест новостей ИИ",
    "tool_review": "Обзор ИИ-инструмента",
    "automation": "Урок по автоматизации",
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


def get_prompt_topic():
    """Задача для рубрики «Промпт дня». Берётся из очереди, а не по номеру недели:
    рубрика выходит трижды в неделю, иначе повторялась бы один и тот же промпт."""
    from topic_bank import next_prompt_topic
    return next_prompt_topic()


def get_trick_topic():
    """Фишка инструмента для рубрики «ИИ за 20 секунд»."""
    from topic_bank import next_trick_topic
    return next_trick_topic()


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
