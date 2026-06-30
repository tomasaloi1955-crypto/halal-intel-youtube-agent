# topic_researcher.py
# AI-агент который сам находит новые темы для уроков по автоматизации бизнеса

import json
import os
import requests
from datetime import datetime
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

from paths import dpath
USED_TOPICS_FILE = dpath("used_topics.json")

# Харам-фильтр — эти категории никогда не используются
HARAM_KEYWORDS = [
    "банк", "bank", "ломбард", "pawn", "алкоголь", "alcohol", "спиртн",
    "свинин", "pork", "сигарет", "tobacco", "cigarette", "казино", "casino",
    "азартн", "gambling", "страхован", "insurance", "крипто", "crypto",
    "нвестиционн фонд", "форекс", "forex", "кредит", "loan shark",
    "микрозайм", "nightclub", "клуб", "бар", "pub",
]

# Стартовый список из 16 тем (недели 1-16)
BASE_TOPICS = [
    {"title": "Цветочный магазин: бот принимает заказы в WhatsApp круглосуточно", "business": "цветочный магазин", "tool": "WhatsApp Bot", "keywords": ["flower shop", "whatsapp bot", "orders"]},
    {"title": "Магазин одежды: автоуведомление 'ваш размер снова есть'", "business": "магазин одежды", "tool": "Telegram Bot", "keywords": ["clothing store", "stock notification", "automation"]},
    {"title": "Халяль-кафе: бот принимает предзаказы без кассира", "business": "халяль кафе", "tool": "Telegram Bot", "keywords": ["halal cafe", "preorder bot", "food"]},
    {"title": "Доставка халяль-еды: клиент сам видит статус заказа", "business": "доставка еды", "tool": "SMS + Bot", "keywords": ["food delivery", "order status", "automation"]},
    {"title": "Салон красоты: онлайн-запись без звонков", "business": "салон красоты", "tool": "Booking Bot", "keywords": ["beauty salon", "online booking", "appointment"]},
    {"title": "Автомастерская: бот напоминает о ТО и возвращает клиента", "business": "автомастерская", "tool": "CRM + Bot", "keywords": ["car service", "reminder bot", "retention"]},
    {"title": "Агентство недвижимости: бот отсеивает нецелевые заявки", "business": "агентство недвижимости", "tool": "Lead Qualification Bot", "keywords": ["real estate", "lead qualification", "chatbot"]},
    {"title": "Грузоперевозки: заявка в боте — диспетчер видит сразу", "business": "грузоперевозки", "tool": "Dispatch Bot", "keywords": ["logistics", "freight", "dispatch automation"]},
    {"title": "Instagram-магазин: бот отвечает на вопросы о цене и наличии", "business": "instagram магазин", "tool": "Instagram Bot", "keywords": ["instagram shop", "dm automation", "ecommerce"]},
    {"title": "Строительная компания: клиент получает смету за 2 минуты", "business": "строительная компания", "tool": "AI Quote Bot", "keywords": ["construction", "quote automation", "estimate"]},
    {"title": "Оптовый склад: покупатель делает заявку в Telegram", "business": "оптовый склад", "tool": "Order Bot", "keywords": ["wholesale", "warehouse", "telegram order"]},
    {"title": "Тур-агентство: бот подбирает халяль-туры по бюджету", "business": "туристическое агентство", "tool": "Travel Bot", "keywords": ["travel agency", "halal travel", "tour bot"]},
    {"title": "Стоматология: напоминания о визите снижают неявки на 60%", "business": "стоматология", "tool": "Reminder Bot", "keywords": ["dental clinic", "appointment reminder", "no-show"]},
    {"title": "Фитнес-зал: бот напоминает об истечении абонемента", "business": "фитнес зал", "tool": "Membership Bot", "keywords": ["gym", "membership renewal", "retention bot"]},
    {"title": "Репетитор: расписание, напоминания и оплата через бот", "business": "репетитор", "tool": "Schedule Bot", "keywords": ["tutor", "schedule automation", "payment bot"]},
    {"title": "Детский центр: родители записывают ребёнка сами", "business": "детский центр", "tool": "Enrollment Bot", "keywords": ["children center", "enrollment", "parent bot"]},
]


def load_used_topics():
    """Load list of already-used business types."""
    if os.path.exists(USED_TOPICS_FILE):
        with open(USED_TOPICS_FILE) as f:
            return json.load(f)
    # Initialize with base 16
    used = [t["business"] for t in BASE_TOPICS]
    save_used_topics(used)
    return used


def save_used_topics(used):
    with open(USED_TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(used, f, ensure_ascii=False, indent=2)


def is_haram(text):
    """Check if topic contains haram keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in HARAM_KEYWORDS)


def search_business_ideas(used_businesses):
    """Use Gemini to research new business automation topics."""
    used_str = ", ".join(used_businesses[-30:])  # last 30 to avoid too long prompt

    prompt = f"""Ты исследователь бизнес-трендов. Твоя задача — найти новые идеи для YouTube-уроков по автоматизации бизнеса.

Канал: "Халяль Интеллидженс" — аудитория предприниматели из СНГ и мусульманского мира.

ВАЖНЫЕ ОГРАНИЧЕНИЯ (строго):
- Только халяль бизнесы
- Исключить НАВСЕГДА: банки, ломбарды, алкоголь, свинина, сигареты, казино, азартные игры, страхование, форекс, ночные клубы
- Бизнесы которые уже использованы: {used_str}

Найди 5 НОВЫХ типов бизнеса из разных сфер (розница, производство, услуги, онлайн, медицина, образование, логистика, сельское хозяйство, IT, общепит).

Думай глобально — СНГ, Турция, ОАЭ, Малайзия, Индонезия, Африка, Европа.
Ищи нестандартные бизнесы которые редко упоминаются в YouTube про автоматизацию.

Для каждого бизнеса придумай конкретную БОЛЬ которую решает автоматизация.

Верни ТОЛЬКО валидный JSON (без markdown):
{{
  "topics": [
    {{
      "business": "тип бизнеса на русском",
      "title": "заголовок урока — Бизнес: что автоматизируем и результат",
      "pain": "конкретная боль владельца бизнеса",
      "solution_concept": "концепция решения без кода — что делает бот/агент",
      "tool": "инструмент (Telegram Bot / WhatsApp Bot / AI Agent / CRM Bot и т.д.)",
      "keywords": ["english keyword 1", "english keyword 2", "english keyword 3"],
      "region": "где актуально (СНГ / Мир / ОАЭ / Юго-Восточная Азия и т.д.)"
    }}
  ]
}}"""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text.strip())
        topics = data.get("topics", [])

        # Filter haram
        clean = []
        for t in topics:
            if is_haram(t.get("business", "") + t.get("title", "")):
                print(f"[FILTER] Удалена харам-тема: {t.get('business')}")
                continue
            if t["business"].lower() in [u.lower() for u in used_businesses]:
                print(f"[FILTER] Уже использована: {t.get('business')}")
                continue
            clean.append(t)

        return clean

    except Exception as e:
        print(f"[RESEARCH] Ошибка поиска тем: {e}")
        return []


def get_next_topic(week_number=None):
    """
    Get topic for current week.
    Weeks 1-16: use BASE_TOPICS.
    Week 17+: research new topics automatically.
    """
    if week_number is None:
        week_number = datetime.now().isocalendar()[1]

    # Weeks 1-16: base topics
    if week_number <= 16:
        idx = (week_number - 1) % 16
        topic = BASE_TOPICS[idx]
        print(f"[SCHEDULE] Неделя {week_number}: базовая тема — {topic['business']}")
        return topic

    # Week 17+: use researched topics
    used = load_used_topics()

    # Check if we have a pre-researched topic for this week
    researched_file = dpath("researched_topics.json")
    researched = []
    if os.path.exists(researched_file):
        with open(researched_file, encoding="utf-8") as f:
            researched = json.load(f)

    if researched:
        topic = researched.pop(0)
        # Save remaining
        with open(researched_file, "w", encoding="utf-8") as f:
            json.dump(researched, f, ensure_ascii=False, indent=2)
        # Mark as used
        used.append(topic["business"])
        save_used_topics(used)
        print(f"[SCHEDULE] Неделя {week_number}: исследованная тема — {topic['business']}")
        return topic

    # No pre-researched topics — research now
    print(f"[RESEARCH] Запас тем закончился, исследуем интернет...")
    new_topics = search_business_ideas(used)

    if not new_topics:
        # Fallback: reuse base topics with different angle
        print("[RESEARCH] Не удалось найти новые темы, берём базовую с другого угла")
        idx = (week_number - 1) % 16
        return BASE_TOPICS[idx]

    # Use first, save rest
    topic = new_topics[0]
    if len(new_topics) > 1:
        with open(researched_file, "w", encoding="utf-8") as f:
            json.dump(new_topics[1:], f, ensure_ascii=False, indent=2)

    used.append(topic["business"])
    save_used_topics(used)

    print(f"[RESEARCH] Новая тема найдена: {topic['business']} ({topic.get('region', 'Мир')})")
    return topic


def prefetch_topics(count=5):
    """Pre-research topics in advance to avoid delays during publishing."""
    used = load_used_topics()

    researched_file = dpath("researched_topics.json")
    existing = []
    if os.path.exists(researched_file):
        with open(researched_file, encoding="utf-8") as f:
            existing = json.load(f)

    if len(existing) >= count:
        print(f"[PREFETCH] Уже есть {len(existing)} тем в запасе, пропускаем.")
        return

    print(f"[PREFETCH] Исследуем новые темы (нужно {count - len(existing)})...")
    all_used = used + [t["business"] for t in existing]
    new = search_business_ideas(all_used)

    combined = existing + new
    with open(researched_file, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    print(f"[PREFETCH] Сохранено {len(combined)} тем в запасе.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--prefetch":
        prefetch_topics(10)
    else:
        # Test: show next 3 topics
        for w in [1, 8, 17, 18, 19]:
            t = get_next_topic(w)
            print(f"\nНеделя {w}: {t['title']}")
            print(f"  Боль: {t.get('pain', t.get('description', ''))}")
