# main.py
import os, re, sys, time, json, schedule, logging
from datetime import datetime
from dotenv import load_dotenv

# Принудительный UTF-8 для вывода — иначе на Windows print('→','✅') падает с UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rss_parser import fetch_latest_news, mark_seen
from ai_processor import process_digest, process_automation, pick_most_interesting
from voice_gen import generate_voice
from video_maker import make_video, create_thumbnail
from youtube_uploader import upload_video
from content_schedule import get_today_content_type, get_automation_topic, get_schedule_info
from telegram_notify import alert_fail, alert_ok

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("agent.log", encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)
OUTPUT_DIR = "output"


def slugify(text, max_len=30):
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:max_len]


def publish_shorts(content, slug):
    """Shorts: ElevenLabs озвучка → Veo3 видео → YouTube."""
    audio_path = os.path.join(OUTPUT_DIR, f"{slug}_shorts.mp3")
    audio = generate_voice(content["shorts_script"], audio_path, is_shorts=True)
    if not audio:
        log.error("Shorts: озвучка не удалась")
        return None

    video = make_video(audio, content["pexels_keywords"], f"{slug}_s",
                       is_shorts=True, script_text=content["shorts_script"])
    if not video:
        log.error("Shorts: монтаж не удался")
        return None

    thumb = os.path.join(OUTPUT_DIR, f"{slug}_s_thumb.jpg")
    create_thumbnail(content["cover_text"], content["cover_subtitle"], thumb,
                     bg_query=" ".join(content.get("pexels_keywords", [])[:2]))

    vid_id = upload_video(video, thumb, content["title_shorts"],
                          content["description"], content["tags"], is_shorts=True)
    if vid_id:
        log.info(f"✅ Shorts: https://youtube.com/shorts/{vid_id}")
        alert_ok(f"Shorts опубликован: https://youtube.com/shorts/{vid_id}")
    else:
        alert_fail("Shorts — заливка", content.get("title_shorts", "")[:60])
    return vid_id


def publish_long(content, slug):
    """
    Длинное видео: твоя озвучка из папки my_voice/ → Veo3 видео → YouTube.
    Агент проверяет папку my_voice/ — если файл есть, монтирует и выгружает.
    """
    audio = generate_voice(content["long_script"], "", is_shorts=False, slug=slug)
    if not audio:
        log.warning(f"⏳ Длинное видео ждёт твою озвучку → положи MP3 в папку my_voice/{slug}.mp3")
        # Сохраняем скрипт чтобы не потерять
        script_path = os.path.join("my_voice", f"{slug}_SCRIPT.txt")
        os.makedirs("my_voice", exist_ok=True)
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(content["long_script"])
        log.info(f"📝 Скрипт сохранён: {script_path}")
        return None

    video = make_video(audio, content["pexels_keywords"], f"{slug}_l",
                       is_shorts=False, script_text=content["long_script"])
    if not video:
        return None

    thumb = os.path.join(OUTPUT_DIR, f"{slug}_l_thumb.jpg")
    create_thumbnail(content["cover_text"], content["cover_subtitle"], thumb,
                     bg_query=" ".join(content.get("pexels_keywords", [])[:2]))

    vid_id = upload_video(video, thumb, content["title_long"],
                          content["description"], content["tags"], is_shorts=False)
    if vid_id:
        log.info(f"✅ Длинное видео: https://youtube.com/watch?v={vid_id}")
    return vid_id


def run_digest():
    log.info("=== ДАЙДЖЕСТ НОВОСТЕЙ ===")
    # Собираем пул и выбираем самую интересную (не помечаем seen до выбора)
    pool = fetch_latest_news(max_articles=12, persist=False)
    if not pool:
        log.info("Нет новых статей")
        return
    log.info(f"Кандидатов: {len(pool)} — выбираю самую интересную...")
    idx = pick_most_interesting(pool)
    article = pool[idx]
    mark_seen(article["link"])  # помечаем использованной только выбранную
    log.info(f"Новость: {article['title'][:70]}")
    content = process_digest(article)
    if not content:
        return
    slug = slugify(article["title"])

    # Shorts каждый день (новости → ElevenLabs). Длинные идут отдельно из очереди.
    publish_shorts(content, slug)


def run_automation():
    log.info("=== УРОК ПО АВТОМАТИЗАЦИИ ===")
    topic = get_automation_topic()
    log.info(f"Тема: {topic['title']}")
    content = process_automation(topic)
    if not content:
        return
    slug = slugify(topic["title"])

    # Shorts — ElevenLabs. Длинные уроки идут из заранее начитанной очереди (run_long_queue).
    publish_shorts(content, slug)


from paths import dpath
QUEUE_FILE = dpath("long_queue.json")
VOICE_DIR = dpath("my_voice")


def _find_recording(slug):
    """Точное совпадение записи озвучки по slug."""
    for ext in ("mp3", "ogg", "wav", "m4a"):
        p = os.path.join(VOICE_DIR, f"{slug}.{ext}")
        if os.path.exists(p):
            return p
    return None


def run_long_queue():
    """
    Публикует заранее начитанные длинные видео из long_queue.json,
    когда наступила дата публикации и есть твоя запись в my_voice/<slug>.<ext>.
    Шортсы по новостям идут отдельно и каждый день.
    """
    if not os.path.exists(QUEUE_FILE):
        return
    try:
        with open(QUEUE_FILE, encoding="utf-8") as f:
            queue = json.load(f)
    except Exception as e:
        log.error(f"Очередь длинных: не читается ({e})")
        return

    today = datetime.now().date().isoformat()
    changed = False

    for item in queue:
        if item.get("published"):
            continue
        if item["publish_date"] > today:
            continue  # ещё рано

        audio = _find_recording(item["slug"])
        if not audio:
            log.warning(f"⏳ Длинное «{item['topic'][:45]}» к публикации ({item['publish_date']}), "
                        f"но нет записи my_voice/{item['slug']}.mp3 — жду.")
            continue

        c = item["content"]
        log.info(f"🎬 Публикую длинное из очереди: {item['topic'][:50]}")
        video = make_video(audio, c["pexels_keywords"], f"{item['slug']}_l",
                           is_shorts=False, script_text=c["long_script"])
        if not video:
            log.error("Длинное: монтаж не удался — повторю в следующий цикл.")
            continue

        thumb = os.path.join(OUTPUT_DIR, f"{item['slug']}_l_thumb.jpg")
        create_thumbnail(c["cover_text"], c["cover_subtitle"], thumb,
                         bg_query=" ".join(c.get("pexels_keywords", [])[:2]))

        vid_id = upload_video(video, thumb, c["title_long"],
                              c["description"], c["tags"], is_shorts=False)
        if vid_id:
            item["published"] = True
            item["video_id"] = vid_id
            changed = True
            log.info(f"✅ Длинное: https://youtube.com/watch?v={vid_id}")
            alert_ok(f"Длинное опубликовано: {item['topic'][:40]}\nhttps://youtube.com/watch?v={vid_id}")
        else:
            log.error("Длинное: заливка не удалась — повторю в следующий цикл.")
            alert_fail("Длинное — заливка", item["topic"][:60])

    if changed:
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)


def run_agent():
    info = get_schedule_info()
    log.info("=" * 55)
    log.info(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} | {info['day']} | {info['label']}")

    try:
        # Shorts по новостям — каждый день
        if get_today_content_type() == "digest":
            run_digest()
        else:
            run_automation()

        # Длинные — из заранее начитанной очереди (по расписанию, 2/нед)
        run_long_queue()
    except Exception as e:
        log.exception("Критический сбой цикла")
        alert_fail("Цикл агента", str(e)[:200])

    log.info("Цикл завершён.")


def start_scheduler():
    log.info("🕌 Халяль Интеллидженс агент запущен")
    log.info("Пн Вт Чт Пт Вс — дайджест | Ср Сб — автоматизация")
    log.info("Shorts → ElevenLabs | Длинные → твоя озвучка из my_voice/")

    run_agent()
    schedule.every().day.at("04:00").do(run_agent)  # 09:00 Алматы = 04:00 UTC

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "--once":
            run_agent()
        elif sys.argv[1] == "--digest":
            run_digest()
        elif sys.argv[1] == "--automation":
            run_automation()
        elif sys.argv[1] == "--check-voice":
            # Проверяет папку my_voice и монтирует если есть файлы
            import glob
            files = glob.glob("my_voice/*.mp3") + glob.glob("my_voice/*.ogg")
            if files:
                log.info(f"Найдено {len(files)} файлов озвучки. Монтируем...")
                run_agent()
            else:
                log.info("Папка my_voice/ пуста. Положи туда MP3 файл.")
    else:
        start_scheduler()
