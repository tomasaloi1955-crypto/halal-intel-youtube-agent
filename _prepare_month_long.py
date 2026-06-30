# Готовит ОЧЕРЕДЬ из 8 длинных видео на месяц (вечные темы по автоматизации).
# Генерит скрипты для начитки + расписание публикации (2 в неделю: Пн и Чт).
# Ты начитываешь все 8 сегодня и кладёшь записи как my_voice/long_01.mp3 ... long_08.mp3
import sys, os, json
from datetime import date, timedelta
for s in (sys.stdout, sys.stderr):
    try: s.reconfigure(encoding="utf-8")
    except Exception: pass

from topic_researcher import BASE_TOPICS
from ai_processor import process_automation
from paths import dpath

VOICE_DIR = dpath("my_voice")
QUEUE_FILE = dpath("long_queue.json")
N = 8                       # сколько видео на месяц
PUBLISH_WEEKDAYS = (0, 3)   # Пн и Чт


def schedule_dates(n):
    """n дат публикации, по будням Пн/Чт, начиная не раньше завтра."""
    days, d = [], date.today() + timedelta(days=1)
    while len(days) < n:
        if d.weekday() in PUBLISH_WEEKDAYS:
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def main():
    os.makedirs(VOICE_DIR, exist_ok=True)
    dates = schedule_dates(N)
    queue = []

    print(f"=== Готовлю {N} длинных видео (вечные темы) ===\n")
    for i in range(N):
        topic = BASE_TOPICS[i]
        slug = f"long_{i+1:02d}"
        print(f"[{i+1}/{N}] {topic['title']}")
        content = process_automation(topic)
        if not content:
            print(f"   ! Не удалось сгенерировать — пропускаю")
            continue

        # Скрипт для начитки
        script_path = os.path.join(VOICE_DIR, f"{slug}_SCRIPT.txt")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(f"# {topic['title']}\n")
            f.write(f"# Запиши и сохрани как: my_voice/{slug}.mp3\n")
            f.write("# (пометки [ПАУЗА], [ИНТРО] и т.п. вслух НЕ читай)\n\n")
            f.write(content["long_script"])

        queue.append({
            "slug": slug,
            "topic": topic["title"],
            "publish_date": dates[i],
            "content": content,
            "published": False,
            "video_id": None,
        })

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

    # Памятка по записи
    guide = os.path.join(VOICE_DIR, "_КАК_ЗАПИСАТЬ.txt")
    with open(guide, "w", encoding="utf-8") as f:
        f.write("КАК ЗАПИСАТЬ ОЗВУЧКУ (8 длинных видео на месяц)\n")
        f.write("=" * 50 + "\n\n")
        f.write("Для каждого ролика открой файл *_SCRIPT.txt, начитай текст\n")
        f.write("и сохрани запись с ТОЧНО таким именем (формат mp3/ogg/wav/m4a):\n\n")
        for q in queue:
            f.write(f"  {q['slug']}.mp3   ← {q['topic']}\n")
            f.write(f"     (публикация: {q['publish_date']})\n\n")
        f.write("\nПометки в скобках ([ПАУЗА], [ИНТРО], [КАК РАБОТАЕТ] и т.п.)\n")
        f.write("читать вслух НЕ нужно — это разметка для тебя.\n")

    print(f"\n=== ГОТОВО: {len(queue)} роликов в очереди ===")
    print(f"Скрипты: {VOICE_DIR}/long_01_SCRIPT.txt ... long_{len(queue):02d}_SCRIPT.txt")
    print(f"Памятка: {guide}")
    print("\nРасписание публикаций:")
    for q in queue:
        print(f"  {q['publish_date']}  {q['slug']}  {q['topic'][:55]}")


if __name__ == "__main__":
    main()
