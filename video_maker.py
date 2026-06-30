# video_maker.py — Veo 3 + Pexels + Pixabay
import requests
import os
import io
import re
import time
import random
import subprocess
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
OUTPUT_DIR = "output"

# Шрифты с поддержкой кириллицы — кросс-платформенно (Windows / Linux / Mac)
_FONT_CANDIDATES = {
    True: [  # bold
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
    False: [  # regular
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
}


def load_font(size, bold=False):
    for path in _FONT_CANDIDATES[bold]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


# Ссылка на ТГ-канал — плашка внизу каждого Shorts
TG_CHANNEL = "t.me/halal_intelligence"
AUTOMATION_BANNER = "Автоматизация бизнес-процессов"


def _ffmpeg_fontfile():
    """
    Шрифт для drawtext. Двоеточие диска (C:) ломает парсер фильтра ffmpeg,
    поэтому копируем шрифт в output/_font.ttf и отдаём относительный путь без двоеточия.
    """
    dst = os.path.join(OUTPUT_DIR, "_font.ttf")
    try:
        if not os.path.exists(dst):
            import shutil
            for src in _FONT_CANDIDATES[True] + _FONT_CANDIDATES[False]:
                if os.path.exists(src):
                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    shutil.copyfile(src, dst)
                    break
        if os.path.exists(dst):
            return dst.replace("\\", "/")
    except Exception as e:
        print(f"[FONT] Не удалось подготовить шрифт для надписей: {e}")
    return None


def _next_shorts_index():
    """Счётчик выпущенных Shorts — нужен чтобы баннер про автоматизацию шёл через раз."""
    p = os.path.join(OUTPUT_DIR, ".shorts_count")
    n = 0
    try:
        if os.path.exists(p):
            n = int((open(p).read().strip() or "0"))
    except Exception:
        n = 0
    n += 1
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(p, "w") as f:
            f.write(str(n))
    except Exception:
        pass
    return n


def _build_overlay_filter(add_automation):
    """drawtext-оверлеи для Shorts: ТГ-канал снизу всегда, автоматизация — опционально (через раз)."""
    font = _ffmpeg_fontfile()
    if not font:
        return None
    parts = [
        f"drawtext=fontfile={font}:text='{TG_CHANNEL}':"
        f"fontcolor=white:fontsize=34:box=1:boxcolor=black@0.55:boxborderw=14:"
        f"x=(w-text_w)/2:y=h-text_h-55"
    ]
    if add_automation:
        parts.append(
            f"drawtext=fontfile={font}:text='{AUTOMATION_BANNER}':"
            f"fontcolor=0xD4AF37:fontsize=36:box=1:boxcolor=black@0.55:boxborderw=14:"
            f"x=(w-text_w)/2:y=95"
        )
    return ",".join(parts)

# ---- ТЕХНО b-roll (канал про технологии): роботы, компьютеры, ИИ, чипы, техно-города, машины ----
BROLL_QUERIES = [
    "humanoid robot", "robot automation factory", "robotic arm assembly",
    "artificial intelligence visualization", "ai neural network abstract",
    "computer code programming screen", "software interface ui animation",
    "data center server room", "semiconductor microchip macro", "circuit board macro",
    "futuristic technology hologram", "digital particles glowing network",
    "self driving electric car", "tesla electric car", "drone flying technology",
    "dubai futuristic skyline night", "shanghai china city night lights",
    "smart city technology aerial", "humanoid robot close up", "automated warehouse robots",
    "glowing cpu processor macro", "abstract data flow visualization",
    "smartphone app interface close up", "laptop keyboard code close up",
]


# Доп. тематические техно-запросы по ключевым словам новости/урока
def _topical_tech(keywords):
    out = []
    for kw in (keywords or [])[:2]:
        if kw:
            out.append(f"{kw} technology")
    return out


def _dt_escape(text):
    """Готовит текст для drawtext: убирает символы, ломающие фильтр ffmpeg."""
    text = text.replace("\\", " ").replace("'", " ").replace(":", " ")
    text = text.replace("%", " процентов ").replace('"', " ")
    text = re.sub(r"[#@{}\[\]]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def generate_captions(script_text, n=10):
    """Gemini делает короткие подписи-акценты (2-4 слова) для ключевых моментов."""
    try:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        m = genai.GenerativeModel("gemini-2.5-flash")
        p = (f"Из текста сделай ровно {n} КОРОТКИХ подписей для экрана (2-4 слова каждая), "
             f"КАПСОМ, без кавычек и нумерации, по одной на строке. Это ключевые моменты по порядку:\n\n"
             f"{script_text[:4000]}")
        r = m.generate_content(p)
        lines = [_dt_escape(l).upper() for l in r.text.splitlines() if l.strip()]
        lines = [l for l in lines if 2 <= len(l) <= 40][:n]
        return lines
    except Exception as e:
        print(f"[CAPTIONS] {e}")
        return []


def _captions_drawtext(captions, duration, w, h):
    """Цепочка drawtext: крупная подпись по очереди в свой временной слот."""
    font = _ffmpeg_fontfile()
    if not font or not captions:
        return None
    slot = duration / len(captions)
    fs = 56 if w >= 1280 else 48
    y = h - 175 if w >= 1280 else h - 270
    parts = []
    for i, cap in enumerate(captions):
        txt = _dt_escape(cap.upper())[:40]
        if not txt:
            continue
        a = i * slot + 0.4
        b = a + min(slot - 0.8, 4.0)
        parts.append(
            f"drawtext=fontfile={font}:text='{txt}':fontcolor=0xFFDD40:fontsize={fs}:"
            f"box=1:boxcolor=black@0.6:boxborderw=18:x=(w-text_w)/2:y={y}:"
            f"enable='between(t,{a:.1f},{b:.1f})'"
        )
    return ",".join(parts) if parts else None


# ---- Лого брендов: показываем фирменный знак при упоминании ----
BRAND_DOMAINS = {
    "telegram": "telegram.org", "телеграм": "telegram.org", "тг ": "telegram.org",
    "whatsapp": "whatsapp.com", "вотсап": "whatsapp.com", "ватсап": "whatsapp.com",
    "instagram": "instagram.com", "инстаграм": "instagram.com",
    "openai": "openai.com", "chatgpt": "openai.com", "чат gpt": "openai.com", "чатгпт": "openai.com",
    "youtube": "youtube.com", "ютуб": "youtube.com",
    "gemini": "google.com", "google": "google.com", "гугл": "google.com",
    "anthropic": "anthropic.com", "claude": "anthropic.com", "клод": "anthropic.com",
    "apple": "apple.com", "эпл": "apple.com", "айфон": "apple.com", "iphone": "apple.com",
    " hp ": "hp.com", "hewlett": "hp.com",
    "microsoft": "microsoft.com", "майкрософт": "microsoft.com", "copilot": "microsoft.com",
    "tesla": "tesla.com", "тесла": "tesla.com",
    "nvidia": "nvidia.com", "нвидиа": "nvidia.com",
    "samsung": "samsung.com", "самсунг": "samsung.com",
    " meta ": "meta.com", "facebook": "meta.com",
    "tiktok": "tiktok.com", "тикток": "tiktok.com",
}


def _logo_chip(im, size=132, pad=20, radius=26):
    """Лого на белой скруглённой плашке — выглядит аккуратно при любом исходнике."""
    im = im.convert("RGBA")
    lw, lh = im.size
    scale = (size - 2 * pad) / max(lw, lh)
    im = im.resize((max(1, int(lw * scale)), max(1, int(lh * scale))), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    card = Image.composite(Image.new("RGBA", (size, size), (255, 255, 255, 255)),
                           Image.new("RGBA", (size, size), (255, 255, 255, 0)), mask)
    card.alpha_composite(im, ((size - im.size[0]) // 2, (size - im.size[1]) // 2))
    return card


def fetch_brand_logos(script_text, slug, max_logos=3):
    """Делает лого-бейджи упомянутых брендов (favicon → белая плашка). Фирменный знак ТГ и т.п."""
    text = " " + script_text.lower() + " "
    found, seen = [], set()
    for kw, domain in BRAND_DOMAINS.items():
        if len(found) >= max_logos:
            break
        if kw in text and domain not in seen:
            seen.add(domain)
            try:
                r = requests.get(
                    f"https://www.google.com/s2/favicons?domain={domain}&sz=128", timeout=15)
                if r.status_code != 200 or len(r.content) < 200:
                    continue
                chip = _logo_chip(Image.open(io.BytesIO(r.content)))
                path = os.path.join(OUTPUT_DIR, f"{slug}_logo_{len(found)}.png")
                chip.save(path)
                found.append(path)
            except Exception as e:
                print(f"[LOGO] {domain}: {e}")
    if found:
        print(f"[LOGO] Бренды на экране: {[os.path.basename(p) for p in found]}")
    return found


def _build_long_overlay(captions, logos, duration, w, h):
    """Собирает filter_complex для длинного видео: подписи + лого. Возвращает (filter, доп.входы)."""
    cap = _captions_drawtext(captions, duration, w, h)
    logos = logos or []
    inputs, segs, cur = [], [], "0:v"

    if cap:
        segs.append(f"[{cur}]{cap}[capv]")
        cur = "capv"

    for k, logo in enumerate(logos):
        idx = 2 + k  # входы: 0=montage, 1=audio, 2..=лого
        inputs += ["-i", logo]
        a = max(1.0, (k + 1) * duration / (len(logos) + 1) - 2.5)
        b = a + 5.0
        segs.append(f"[{idx}:v]scale=-1:120[lg{k}]")
        segs.append(f"[{cur}][lg{k}]overlay=W-w-45:45:"
                    f"enable='between(t,{a:.1f},{b:.1f})'[ov{k}]")
        cur = f"ov{k}"

    if not segs:
        return None, []

    # Переименовываем последнюю выходную метку в [outv]
    segs[-1] = re.sub(rf"\[{cur}\]$", "[outv]", segs[-1])
    return ";".join(segs), inputs


# Сцены для Veo 3 по теме
VEO3_SCENE_PROMPTS = {
    "openai":     "Futuristic AI neural network glowing blue circuits, cinematic, 4K",
    "anthropic":  "Abstract AI consciousness golden light particles flowing, cinematic",
    "chatgpt":    "Digital conversation interface holographic display, dark background, cinematic",
    "claude":     "Elegant AI assistant golden amber light, neural patterns, cinematic",
    "gemini":     "Google DeepMind AI colorful data streams, cinematic 4K",
    "robot":      "Humanoid robot in modern office, photorealistic, cinematic",
    "автоматизация": "Business automation workflow glowing connections, dark background, cinematic",
    "бизнес":     "Modern entrepreneur using AI holographic display, cinematic",
    "цветочный":  "Beautiful flower shop with digital ordering system, warm lighting, cinematic",
    "салон":      "Modern beauty salon with digital booking system, cinematic",
    "default":    "Futuristic AI technology abstract visualization, dark background, golden light, cinematic 4K",
}


def detect_scene_prompt(keywords, script_text=""):
    text = " ".join(keywords).lower() + " " + script_text[:300].lower()
    for key, prompt in VEO3_SCENE_PROMPTS.items():
        if key != "default" and key in text:
            return prompt
    return VEO3_SCENE_PROMPTS["default"]


def generate_veo3_clip(prompt, output_path, max_wait=120):
    """Generate video clip using Google Veo 3 via Gemini API."""
    try:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

        print(f"[VEO3] Генерирую клип: {prompt[:60]}...")

        # Use Veo 3 via Gemini
        model = genai.ImageGenerationModel("veo-003")
        operation = model.generate_videos(
            prompt=prompt,
            config=genai.GenerateVideosConfig(
                aspect_ratio="16:9",
                duration_seconds=8,
                number_of_videos=1,
            )
        )

        # Wait for completion
        start = time.time()
        while not operation.done:
            if time.time() - start > max_wait:
                print("[VEO3] Timeout — переключаемся на Pexels")
                return None
            time.sleep(5)
            operation.refresh()

        if operation.result and operation.result.generated_videos:
            video = operation.result.generated_videos[0]
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(video.video.video_bytes)
            print(f"[VEO3] Клип сохранён: {output_path}")
            return output_path

    except Exception as e:
        print(f"[VEO3] Ошибка: {e} — переключаемся на Pexels")
    return None


def fetch_pexels_videos(query, count=8):
    clips = []
    headers = {"Authorization": PEXELS_API_KEY}
    try:
        url = (f"https://api.pexels.com/videos/search?query={query}"
               f"&per_page=15&orientation=landscape&size=medium")
        resp = requests.get(url, headers=headers, timeout=15)
        data = resp.json()
        for video in data.get("videos", []):
            for vf in video.get("video_files", []):
                if vf.get("quality") in ["hd", "sd"] and vf.get("width", 0) >= 1280:
                    clips.append({"url": vf["link"]})
                    break
            if len(clips) >= count:
                break
    except Exception as e:
        print(f"[PEXELS] Error: {e}")
    return clips


def fetch_diverse_clips(queries, target, slug):
    """Качает МНОГО уникальных предметных клипов из разных запросов — чтобы видео не повторялось."""
    paths, seen = [], set()
    for q in queries:
        if len(paths) >= target:
            break
        for clip in fetch_pexels_videos(q, count=6):
            u = clip["url"]
            if u in seen:
                continue
            seen.add(u)
            p = os.path.join(OUTPUT_DIR, f"{slug}_bc_{len(paths)}.mp4")
            if download_media(u, p):
                paths.append(p)
            if len(paths) >= target:
                break
    print(f"[VIDEO] Собрано уникальных клипов: {len(paths)} (цель {target})")
    return paths


def fetch_pexels_photos(query, count=3):
    photos = []
    headers = {"Authorization": PEXELS_API_KEY}
    try:
        url = f"https://api.pexels.com/v1/search?query={query}&per_page=5&orientation=landscape"
        resp = requests.get(url, headers=headers, timeout=15)
        data = resp.json()
        for photo in data.get("photos", []):
            src = photo.get("src", {})
            img_url = src.get("large2x") or src.get("large")
            if img_url:
                photos.append({"url": img_url})
            if len(photos) >= count:
                break
    except Exception as e:
        print(f"[PEXELS PHOTO] Error: {e}")
    return photos


def download_media(url, path):
    try:
        resp = requests.get(url, stream=True, timeout=30)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return path
    except Exception as e:
        print(f"[DOWNLOAD] Error: {e}")
        return None


def photo_to_video(photo_path, duration=5, output_path=None):
    if not output_path:
        output_path = photo_path.rsplit(".", 1)[0] + "_vid.mp4"
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", photo_path,
        "-vf", f"scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,zoompan=z='min(zoom+0.001,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={duration*24}:s=1280x720,fps=24",
        "-t", str(duration), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-pix_fmt", "yuv420p", output_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode == 0:
            return output_path
    except Exception as e:
        print(f"[KEN BURNS] Error: {e}")
    return None


def create_title_card(text, output_path):
    try:
        img = Image.new("RGB", (1920, 1080), color=(5, 5, 20))
        draw = ImageDraw.Draw(img)
        for y in range(1080):
            ratio = y / 1080
            draw.line([(0, y), (1920, y)], fill=(int(5+ratio*15), int(5+ratio*10), int(20+ratio*50)))
        draw.rectangle([0, 0, 8, 1080], fill=(212, 175, 55))
        font = load_font(80, bold=True)
        font_sm = load_font(36)
        words = text.split()
        lines, current = [], ""
        for word in words:
            test = current + " " + word if current else word
            if len(test) > 30:
                lines.append(current)
                current = word
            else:
                current = test
        if current:
            lines.append(current)
        y_start = 540 - len(lines) * 50
        for line in lines:
            draw.text((960, y_start), line, font=font, fill=(212, 175, 55), anchor="mm")
            y_start += 100
        draw.text((960, 1030), "Халяль Интеллидженс", font=font_sm, fill=(100, 100, 120), anchor="mm")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        img.save(output_path, "JPEG", quality=92)
        return output_path
    except Exception as e:
        print(f"[TITLE CARD] Error: {e}")
        return None


def get_media_duration(path, default=50.0):
    """Длительность медиафайла в секундах через ffprobe."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception as e:
        print(f"[FFPROBE] Не удалось определить длительность ({e}), беру {default}с")
        return default


def assemble_video(audio_path, media_clips, output_path, is_shorts=False,
                   add_automation=False, captions=None, logos=None):
    """
    Два прохода:
    1) Склейка клипов в montage.mp4. Для длинных — каждый клип обрезается до короткого
       сегмента, чтобы из множества клипов собрать дорожку ≈ длины аудио (без повторов).
       Для Shorts — целый кадр по центру + размытый фон.
    2) montage зацикливаем под длину аудио, добавляем звук и оверлеи:
       Shorts → ТГ-плашка/баннер; длинные → крупные подписи + лого брендов.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    w, h = (720, 1280) if is_shorts else (1280, 720)
    duration = get_media_duration(audio_path)
    n = max(1, len(media_clips))

    # Для длинных: сегмент на клип так, чтобы покрыть всю длину (минимум повторов)
    seg = None
    if not is_shorts:
        seg = max(6.0, min(15.0, duration / n))

    # --- Проход 1: нормализуем/обрезаем и склеиваем ---
    montage = os.path.join(OUTPUT_DIR, "_montage.mp4")
    inputs, filters = [], []
    for i, cp in enumerate(media_clips):
        inputs += ["-i", cp]
        if is_shorts:
            filters.append(
                f"[{i}:v]split=2[bg{i}s][fg{i}s];"
                f"[bg{i}s]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                f"scale=90:-2,scale={w}:{h},setsar=1[bg{i}];"
                f"[fg{i}s]scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[fg{i}];"
                f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=24[v{i}]"
            )
        else:
            filters.append(
                f"[{i}:v]trim=0:{seg:.1f},setpts=PTS-STARTPTS,"
                f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},setsar=1,fps=24[v{i}]"
            )
    concat_in = "".join(f"[v{i}]" for i in range(n))
    filter_complex = ";".join(filters) + f";{concat_in}concat=n={n}:v=1:a=0[outv]"

    cmd1 = ["ffmpeg", "-y", *inputs,
            "-filter_complex", filter_complex, "-map", "[outv]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
            "-pix_fmt", "yuv420p", montage]
    try:
        r1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=1500)
        if r1.returncode != 0:
            print(f"[VIDEO] Монтаж (проход 1) ошибка: {r1.stderr[-400:]}")
            return None
    except Exception as e:
        print(f"[VIDEO] Монтаж (проход 1) исключение: {e}")
        return None

    # --- Проход 2: длина под аудио + звук + оверлеи ---
    if is_shorts:
        overlay, extra_inputs = _build_overlay_filter(add_automation), []
        overlay = f"[0:v]{overlay}[outv]" if overlay else None
    else:
        overlay, extra_inputs = _build_long_overlay(captions, logos, duration, w, h)

    def run_pass2(use_overlay):
        cmd2 = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", montage, "-i", audio_path]
        if use_overlay and overlay:
            cmd2 += [*extra_inputs, "-filter_complex", overlay,
                     "-map", "[outv]", "-map", "1:a:0"]
        else:
            cmd2 += ["-map", "0:v:0", "-map", "1:a:0"]
        cmd2 += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                 "-c:a", "aac", "-b:a", "192k", "-t", f"{duration:.2f}",
                 "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path]
        return subprocess.run(cmd2, capture_output=True, text=True, timeout=1500)

    try:
        r2 = run_pass2(use_overlay=True)
        if r2.returncode != 0 and overlay:
            print(f"[VIDEO] Оверлей не сработал, собираю без него: {r2.stderr[-200:]}")
            r2 = run_pass2(use_overlay=False)
        if r2.returncode == 0:
            print(f"[VIDEO] Готово: {output_path}")
            return output_path
        print(f"[VIDEO] FFmpeg error (проход 2): {r2.stderr[-400:]}")
    except Exception as e:
        print(f"[VIDEO] Error: {e}")
    return None


def _build_queries(pexels_keywords):
    """Техно-видеоряд в приоритете (роботы/компьютеры/чипы) + максимум 1 тематический запрос."""
    pool = list(BROLL_QUERIES)
    random.shuffle(pool)
    topical = _topical_tech(pexels_keywords)[:1]  # тематику по минимуму — больше техно/роботов
    return (pool + topical)[:20]


def make_video(audio_path, pexels_keywords, title_slug, is_shorts=False, script_text=""):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    duration = get_media_duration(audio_path)
    queries = _build_queries(pexels_keywords)

    if is_shorts:
        # Shorts: немного предметных клипов (короткое видео)
        clips = fetch_diverse_clips(queries, target=6, slug=f"{title_slug}_s")
        captions, logos = None, None
    else:
        # Длинное: много уникальных клипов под всю длину + подписи + лого брендов
        target = min(45, max(14, int(duration / 10) + 4))
        clips = fetch_diverse_clips(queries, target=target, slug=title_slug)
        print("[VIDEO] Генерирую подписи-акценты...")
        captions = generate_captions(script_text, n=12)
        logos = fetch_brand_logos(script_text, title_slug)

    # Резерв: если клипов мало — фото с Ken Burns
    if len(clips) < 2:
        photos = fetch_pexels_photos(f"technology {(' '.join(pexels_keywords))[:30]}", count=3)
        for i, photo in enumerate(photos):
            pp = os.path.join(OUTPUT_DIR, f"{title_slug}_ph_{i}.jpg")
            if download_media(photo["url"], pp):
                vid = photo_to_video(pp, duration=5)
                if vid:
                    clips.append(vid)

    if not clips:
        print("[VIDEO] Нет медиафайлов")
        return None

    suffix = "shorts" if is_shorts else "long"
    output_path = os.path.join(OUTPUT_DIR, f"{title_slug}_{suffix}.mp4")
    add_automation = bool(is_shorts and (_next_shorts_index() % 2 == 1))
    return assemble_video(audio_path, clips, output_path, is_shorts,
                          add_automation=add_automation, captions=captions, logos=logos)


def _wrap_text(draw, text, font, max_width):
    """Разбивает текст на строки по ширине (для обложки)."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _thumbnail_background(bg_query, W, H):
    """Фон обложки: затемнённое фото с Pexels (для кликабельности) или резервный градиент."""
    if bg_query:
        try:
            photos = fetch_pexels_photos(bg_query, count=1)
            if photos:
                tmp = os.path.join(OUTPUT_DIR, "_thumb_bg.jpg")
                if download_media(photos[0]["url"], tmp):
                    bg = Image.open(tmp).convert("RGB")
                    scale = max(W / bg.width, H / bg.height)
                    bg = bg.resize((max(W, int(bg.width * scale)), max(H, int(bg.height * scale))))
                    left, top = (bg.width - W) // 2, (bg.height - H) // 2
                    bg = bg.crop((left, top, left + W, top + H))
                    # затемняем, чтобы текст читался поверх фото
                    return Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.55)
        except Exception as e:
            print(f"[THUMBNAIL BG] {e} — беру градиент")
    img = Image.new("RGB", (W, H), (5, 5, 20))
    d = ImageDraw.Draw(img)
    for y in range(H):
        r = y / H
        d.line([(0, y), (W, y)], fill=(int(5 + r * 15), int(5 + r * 10), int(20 + r * 50)))
    return img


def create_thumbnail(cover_text, cover_subtitle, output_path, bg_query=None):
    """
    Фирменная обложка в стиле образца (HTML/CSS: градиент + 3D-текст + ведущая).
    Если HTML-рендер недоступен — запасной вариант на PIL (фото-фон + текст).
    """
    try:
        from thumbnail_html import render as _render_html
        if _render_html(cover_text, cover_subtitle, output_path):
            print(f"[THUMBNAIL] Готово (HTML-шаблон): {output_path}")
            return output_path
        print("[THUMBNAIL] HTML-рендер не дал результат, беру запасной PIL")
    except Exception as e:
        print(f"[THUMBNAIL] HTML недоступен ({e}), беру запасной PIL")

    try:
        W, H = 1280, 720
        img = _thumbnail_background(bg_query, W, H)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 14, H], fill=(212, 175, 55))  # золотая полоса слева

        # Заголовок — крупно, заглавными, с чёрной обводкой (читается на любом фоне)
        text = (cover_text or "").upper()
        size = 112
        font_big = load_font(size, bold=True)
        lines = _wrap_text(draw, text, font_big, W - 170)
        while len(lines) > 3 and size > 60:
            size -= 10
            font_big = load_font(size, bold=True)
            lines = _wrap_text(draw, text, font_big, W - 170)
        line_h = size + 14
        y = (H - len(lines) * line_h) // 2 - 30
        for line in lines:
            draw.text((W // 2, y), line, font=font_big, fill=(255, 221, 64),
                      anchor="ma", stroke_width=6, stroke_fill=(0, 0, 0))
            y += line_h

        # Подзаголовок — белым в красной плашке (акцент)
        sub = (cover_subtitle or "").upper()
        if sub:
            font_sub = load_font(50, bold=True)
            tw = draw.textlength(sub, font=font_sub)
            bx, by = (W - tw) // 2 - 26, y + 8
            draw.rectangle([bx, by, bx + tw + 52, by + 78], fill=(200, 30, 30))
            draw.text((W // 2, by + 39), sub, font=font_sub, fill=(255, 255, 255), anchor="mm")

        # Бренд внизу
        font_sm = load_font(34, bold=True)
        draw.text((W // 2, H - 32), "Халяль Интеллидженс", font=font_sm,
                  fill=(235, 235, 245), anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        img.save(output_path, "JPEG", quality=95)
        return output_path
    except Exception as e:
        print(f"[THUMBNAIL] Error: {e}")
        return None
