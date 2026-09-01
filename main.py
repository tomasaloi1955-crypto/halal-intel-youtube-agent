# main.py
import os, re, sys, time, json, glob, schedule, logging
from datetime import datetime
from dotenv import load_dotenv

# Принудительный UTF-8 для вывода — иначе на Windows print('→','✅') падает с UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rss_parser import fetch_latest_news, mark_seen, fetch_article_text
from ai_processor import process_digest, process_automation, process_tool_review, pick_most_interesting
from voice_gen import generate_voice
from video_maker import make_video, create_thumbnail
from youtube_uploader import upload_video
from tiktok_uploader import upload_to_tiktok
from threads_poster import post_once as threads_post_once, generate_post as generate_social_post
from instagram_poster import post_once as instagram_post_once
from content_schedule import get_today_content_type, get_automation_topic, get_tool_review_topic, get_schedule_info
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


def cleanup_raw_assets(slug):
    """Вызывать ТОЛЬКО после подтверждённой публикации (vid_id получен от YouTube).
    Удаляет исходники b-roll (_bc_), Ken Burns фото (_ph_) и лого (_logo_) — они уже
    вшиты в финальное видео. Финальный *_shorts.mp4/*_long.mp4 и обложку не трогает —
    их имена не содержат этих меток, так что под шаблоны они не попадают."""
    patterns = [f"{slug}*_bc_*.mp4", f"{slug}*_ph_*.jpg", f"{slug}*_ph_*_vid.mp4",
                f"{slug}*_logo_*.png"]
    for pat in patterns:
        for p in glob.glob(os.path.join(OUTPUT_DIR, pat)):
            try:
                os.remove(p)
            except OSError:
                pass


def publish_shorts(content, slug):
    """Shorts: ElevenLabs озвучка → Veo3 видео → YouTube."""
    audio_path = os.path.join(OUTPUT_DIR, f"{slug}_shorts.mp3")
    audio = generate_voice(content["shorts_script"], audio_path, is_shorts=True)
    if not audio:
        log.error("Shorts: озвучка не удалась")
        alert_fail("Shorts — озвучка (ElevenLabs)", content.get("title_shorts", "")[:60])
        return None

    video = make_video(audio, content["pexels_keywords"], f"{slug}_s",
                       is_shorts=True, script_text=content["shorts_script"])
    if not video:
        log.error("Shorts: монтаж не удался")
        alert_fail("Shorts — монтаж видео", content.get("title_shorts", "")[:60])
        return None

    thumb = os.path.join(OUTPUT_DIR, f"{slug}_s_thumb.jpg")
    create_thumbnail(content["cover_text"], content["cover_subtitle"], thumb,
                     bg_query=" ".join(content.get("pexels_keywords", [])[:2]))

    vid_id = upload_video(video, thumb, content["title_shorts"],
                          content["description"], content["tags"], is_shorts=True)
    if vid_id:
        log.info(f"✅ Shorts: https://youtube.com/shorts/{vid_id}")
        alert_ok(f"Shorts опубликован: https://youtube.com/shorts/{vid_id}")
        cleanup_raw_assets(slug)
    else:
        alert_fail("Shorts — заливка", content.get("title_shorts", "")[:60])

    # Тот же вертикальный ролик — в TikTok (пропускается, если TikTok не настроен)
    try:
        tags = content.get("tags", []) or []
        caption = content.get("title_shorts", "")[:150] + " " + " ".join(f"#{t.replace(' ', '')}" for t in tags[:5])
        pid = upload_to_tiktok(video, caption=caption.strip())
        if pid:
            log.info(f"✅ TikTok: черновик отправлен (publish_id={pid})")
    except Exception as e:
        log.error(f"TikTok публикация: {e}")

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
        cleanup_raw_assets(slug)
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

    # RSS даёт только тизер в 1-2 предложения без единого факта — этого не хватает,
    # чтобы написать содержательный сценарий. Дочитываем саму статью для выбранной новости
    # (только для неё одной — не тратим время на весь пул из 12 кандидатов).
    full_text = fetch_article_text(article["link"])
    if full_text and len(full_text) > len(article.get("summary", "")):
        log.info(f"Полный текст статьи получен ({len(full_text)} симв.) — используем вместо тизера")
        article = {**article, "summary": full_text}
    else:
        log.warning("Полный текст статьи не получен — работаю с коротким RSS-тизером")

    content = process_digest(article)
    if not content:
        log.error("Дайджест: генерация сценария не удалась (см. лог выше — часто это квота Gemini)")
        alert_fail("Дайджест — генерация сценария (Gemini)", article["title"][:60])
        return None
    slug = slugify(article["title"])

    # Shorts каждый день (новости → ElevenLabs). Длинные идут отдельно из очереди.
    vid_id = publish_shorts(content, slug)
    if vid_id:
        content["_video_id"] = vid_id  # чтобы соцсети взяли настоящую обложку видео
    return content


def run_automation():
    log.info("=== УРОК ПО АВТОМАТИЗАЦИИ ===")
    topic = get_automation_topic()
    log.info(f"Тема: {topic['title']}")
    content = process_automation(topic)
    if not content:
        log.error("Автоматизация: генерация сценария не удалась (см. лог выше — часто это квота Gemini)")
        alert_fail("Автоматизация — генерация сценария (Gemini)", topic["title"][:60])
        return None
    slug = slugify(topic["title"])

    # Shorts — ElevenLabs. Длинные уроки идут из заранее начитанной очереди (run_long_queue).
    vid_id = publish_shorts(content, slug)
    if vid_id:
        content["_video_id"] = vid_id  # чтобы соцсети взяли настоящую обложку видео
    return content


def run_tool_review():
    log.info("=== ОБЗОР ИИ-ИНСТРУМЕНТА ===")
    topic = get_tool_review_topic()
    log.info(f"Инструмент: {topic['tool_name']}")
    content = process_tool_review(topic)
    if not content:
        log.error("Обзор инструмента: генерация сценария не удалась (см. лог выше — часто это квота Gemini)")
        alert_fail("Обзор инструмента — генерация сценария (Gemini)", topic["title"][:60])
        return None
    slug = slugify(topic["title"])

    vid_id = publish_shorts(content, slug)
    if vid_id:
        content["_video_id"] = vid_id  # чтобы соцсети взяли настоящую обложку видео
    return content


from paths import dpath
import shutil
QUEUE_FILE = dpath("long_queue.json")
VOICE_DIR = dpath("my_voice")
SEED_QUEUE = "seed/queue_seed.json"


def _seed_data():
    """На свежем диске (Render) разворачиваем стартовую очередь из seed/ в DATA_DIR."""
    try:
        if not os.path.exists(QUEUE_FILE) and os.path.exists(SEED_QUEUE):
            os.makedirs(os.path.dirname(QUEUE_FILE) or ".", exist_ok=True)
            shutil.copyfile(SEED_QUEUE, QUEUE_FILE)
            log.info("Очередь длинных развёрнута из seed/")
    except Exception as e:
        log.error(f"seed error: {e}")


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
        # Если локального файла нет, но есть ссылка из Telegram — скачиваем сейчас
        if not audio and item.get("audio_file_id"):
            ext = item.get("audio_ext", "oga")
            dest = os.path.join(VOICE_DIR, f"{item['slug']}.{ext}")
            try:
                from telegram_intake import download_by_file_id
                if download_by_file_id(item["audio_file_id"], dest):
                    audio = dest
                    log.info(f"Озвучка скачана из Telegram: {item['slug']}")
            except Exception as e:
                log.error(f"Не удалось скачать озвучку из Telegram: {e}")
        if not audio:
            log.warning(f"⏳ Длинное «{item['topic'][:45]}» к публикации ({item['publish_date']}), "
                        f"но озвучки ещё нет — жду (пришли аудио боту).")
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
            cleanup_raw_assets(item["slug"])
        else:
            log.error("Длинное: заливка не удалась — повторю в следующий цикл.")
            alert_fail("Длинное — заливка", item["topic"][:60])

    if changed:
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)


def run_agent():
    _seed_data()
    info = get_schedule_info()
    log.info("=" * 55)
    log.info(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} | {info['day']} | {info['label']}")

    todays_content = None
    try:
        # Shorts — каждый день, тип по расписанию (новости / обзор инструмента / автоматизация)
        content_type = get_today_content_type()
        if content_type == "digest":
            todays_content = run_digest()
        elif content_type == "tool_review":
            todays_content = run_tool_review()
        else:
            todays_content = run_automation()

        # Длинные — из заранее начитанной очереди (по расписанию, 2/нед)
        run_long_queue()
    except Exception as e:
        log.exception("Критический сбой цикла")
        alert_fail("Цикл агента", str(e)[:200])

    # Текстовый пост — раз в день, на реальном факте сегодняшнего видео, с настоящей обложкой
    # видео как картинкой (если контента нет — сработает резервная тема внутри generate_social_post).
    # Генерация — ОДНА на обе площадки (не тратим второй вызов ИИ и не расходимся в смысле),
    # а публикация в Threads и Instagram друг от друга не зависит: выключен/не настроен один —
    # второй всё равно получит готовый пост.
    social_text = social_image = None
    try:
        social_text, social_image = generate_social_post(todays_content)
    except Exception as e:
        log.error(f"Генерация соц-поста: {e}")

    if social_text:
        try:
            threads_post_once(text=social_text, image_url=social_image)
        except Exception as e:
            log.error(f"Threads пост: {e}")
        try:
            instagram_post_once(text=social_text, image_url=social_image)
        except Exception as e:
            log.error(f"Instagram пост: {e}")

    log.info("Цикл завершён.")


def start_scheduler():
    log.info("🕌 Халяль Интеллидженс агент запущен")
    log.info("Пн Чт Вс — новости ИИ | Вт Пт — обзор ИИ-инструмента | Ср Сб — автоматизация")
    log.info("Shorts → ElevenLabs | Длинные → твоя озвучка из my_voice/")

    _seed_data()  # развернуть очередь на свежем диске (Render) до старта приёма

    # Telegram-приём озвучек (/next → текст, аудио → сохранение) фоновым потоком
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        import threading
        from telegram_intake import poll_loop
        threading.Thread(target=poll_loop, daemon=True).start()
        log.info("📩 Telegram-интейк озвучек включён")

    run_agent()
    schedule.every().day.at("04:00").do(run_agent)  # 09:00 Алматы = 04:00 UTC

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "--once":
            _seed_data()
            # Разовый опрос Telegram — забрать присланные озвучки (для GitHub Actions)
            try:
                from telegram_intake import poll_once
                poll_once()
            except Exception as e:
                log.error(f"tg poll_once: {e}")
            run_agent()
        elif sys.argv[1] == "--digest":
            run_digest()
        elif sys.argv[1] == "--automation":
            run_automation()
        elif sys.argv[1] == "--tool-review":
            run_tool_review()
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
