# post_media.py — фото-обложка и короткое видео к посту-примеру для чужого канала.
#
# ЗАЧЕМ. Владельцы каналов (рецепты, магазины, школы) постят фото + текст, а не голый
# текст. Пример без картинки выглядит «не как у них» и продаёт хуже. Поэтому к каждому
# из 3 примеров example_generator.py делает:
#   • обложку 1080×1080 — настоящее фото по теме поста + крупный заголовок;
#   • вертикальное видео 1080×1920, ~8 секунд — живой клип по теме + тот же заголовок.
#
# ОТКУДА КАДРЫ. Только настоящие стоковые фото/видео Pexels (ключ PEXELS_API_KEY уже
# есть у автопилота). ИИ-генерацию картинок НЕ используем — она отключена 18.09.2026,
# потому что не гарантирует кадр без людей (подробности — в шапке threads_poster.py).
# У стока есть описание кадра (alt у фото, адрес страницы у видео): по нему отсеиваем
# людей и харам. Не нашлось подходящего кадра — обложка рисуется без фото (post_card
# не нужен: делаем простую фирменную плашку), а видео не делается.
#
#   from post_media import make_post_media
#   media = make_post_media("Овсяное печенье с бананом", "oatmeal cookies banana", "out/1")
#   # {"photo": "out/1.jpg", "video": "out/1.mp4"}  (любой из путей может быть None)
import os
import re
import shutil
import subprocess

import requests
from PIL import Image, ImageDraw, ImageFilter

from video_maker import PEXELS_API_KEY, download_media, load_font

COVER = 1080
VIDEO_W, VIDEO_H = 1080, 1920
VIDEO_SECONDS = 8

# Слова в описании кадра, из-за которых кадр не берём. Руки тоже: «без людей» —
# значит без людей совсем, на кулинарном стоке хватает кадров без рук.
BANNED_WORDS = [
    "person", "people", "man", "men", "woman", "women", "girl", "boy", "child", "children",
    "kid", "baby", "lady", "guy", "face", "portrait", "model", "hand", "hands", "finger",
    "couple", "family", "friends", "chef", "cook", "baker", "barista", "student", "teacher",
    "mother", "father", "bride", "selfie", "body", "legs", "bikini",
    "wine", "beer", "alcohol", "cocktail", "whiskey", "vodka", "champagne", "liquor", "bar",
    "pork", "bacon", "ham", "sausage", "salami", "pepperoni",
    "casino", "gambling", "poker", "cross", "church", "christmas",
]
_BANNED_RE = re.compile(r"\b(" + "|".join(BANNED_WORDS) + r")s?\b", re.I)


def _clean(description):
    """True, если по описанию кадр можно ставить в пост."""
    return bool(description) and not _BANNED_RE.search(description.replace("-", " "))


def _ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"


# ── поиск кадров ─────────────────────────────────────────────────────────────

def find_photo(query):
    """URL подходящего фото или None. Описание кадра на Pexels — поле alt."""
    if not PEXELS_API_KEY or not query:
        return None
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 30, "orientation": "square"},
            headers={"Authorization": PEXELS_API_KEY}, timeout=20,
        )
        for photo in resp.json().get("photos", []):
            if _clean(photo.get("alt", "")):
                src = photo.get("src", {})
                return src.get("large2x") or src.get("large")
    except Exception as e:
        print(f"[media] Pexels фото недоступен: {e}")
    return None


def find_video(query):
    """URL подходящего вертикального клипа или None. У видео Pexels нет alt, но адрес
    страницы — это описание кадра: pexels.com/video/close-up-of-cookies-123/."""
    if not PEXELS_API_KEY or not query:
        return None
    try:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": 30, "orientation": "portrait", "size": "medium"},
            headers={"Authorization": PEXELS_API_KEY}, timeout=20,
        )
        for video in resp.json().get("videos", []):
            slug = (video.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
            if not _clean(re.sub(r"-?\d+$", "", slug)) or video.get("duration", 0) < 4:
                continue
            files = [f for f in video.get("video_files", [])
                     if f.get("height", 0) >= 1280 and f.get("height", 0) > f.get("width", 0)]
            if files:
                return min(files, key=lambda f: f["height"])["link"]  # самый лёгкий из годных
    except Exception as e:
        print(f"[media] Pexels видео недоступен: {e}")
    return None


# ── обложка ──────────────────────────────────────────────────────────────────

def _wrap(draw, text, fnt, max_w):
    lines, cur = [], ""
    for word in text.split():
        test = f"{cur} {word}".strip()
        if draw.textlength(test, font=fnt) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit_title(draw, title, max_w, max_lines=3, start=96, smallest=52):
    """Самый крупный кегль, при котором заголовок влезает в max_lines строк."""
    for size in range(start, smallest - 1, -4):
        fnt = load_font(size, bold=True)
        lines = _wrap(draw, title, fnt, max_w)
        if len(lines) <= max_lines:
            return fnt, lines, size
    return fnt, lines[:max_lines], smallest


def _fill(img, w, h):
    """Обрезает картинку до w×h по центру без искажений."""
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _title_overlay(w, h, title, caption, top_fraction):
    """Прозрачный слой: затемнение снизу + заголовок + подпись канала."""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    start = int(h * top_fraction)
    for y in range(start, h):
        alpha = min(215, int(215 * (y - start) / (h - start) * 1.6))
        draw.line([(0, y), (w, y)], fill=(20, 12, 8, alpha))

    pad = int(w * 0.07)
    fnt, lines, size = _fit_title(draw, title.upper(), w - 2 * pad)
    line_h = int(size * 1.12)
    small = load_font(max(26, size // 3))
    y = h - pad - int(size * 0.6) - line_h * len(lines) - (size // 2 if caption else 0)
    for line in lines:
        draw.text((pad + 3, y + 3), line, font=fnt, fill=(0, 0, 0, 140))
        draw.text((pad, y), line, font=fnt, fill=(255, 255, 255, 255))
        y += line_h
    if caption:
        draw.text((pad, y + size // 4), caption, font=small, fill=(255, 226, 180, 255))
    return layer


def make_cover(title, photo_path, out_path, caption=""):
    """Обложка 1080×1080: фото + заголовок. Без фото — тёплый однотонный фон."""
    if photo_path:
        base = _fill(Image.open(photo_path).convert("RGB"), COVER, COVER)
    else:
        base = Image.new("RGB", (COVER, COVER), (196, 142, 96))
        base = base.filter(ImageFilter.GaussianBlur(2))
    over = _title_overlay(COVER, COVER, title, caption, top_fraction=0.35)
    Image.alpha_composite(base.convert("RGBA"), over).convert("RGB").save(out_path, "JPEG", quality=90)
    return out_path


def make_video(title, clip_path, out_path, caption=""):
    """Вертикальный ролик: клип обрезается до 9:16, поверх — заголовок. Без звука:
    Telegram и так запускает видео в ленте без звука."""
    overlay = out_path.rsplit(".", 1)[0] + "_overlay.png"
    _title_overlay(VIDEO_W, VIDEO_H, title, caption, top_fraction=0.5).save(overlay)
    cmd = [
        _ffmpeg(), "-y", "-i", clip_path, "-loop", "1", "-i", overlay,
        "-filter_complex",
        f"[0:v]scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},fps=30,setsar=1[v];"
        f"[1:v]format=rgba,fade=t=in:st=0.3:d=0.7:alpha=1[t];[v][t]overlay=0:0:shortest=1",
        "-t", str(VIDEO_SECONDS), "-an", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=180)
        if result.returncode == 0:
            return out_path
        print(f"[media] ffmpeg: {result.stderr.decode(errors='ignore')[-400:]}")
    except Exception as e:
        print(f"[media] Видео не собрано: {e}")
    finally:
        if os.path.exists(overlay):
            os.remove(overlay)
    return None


def make_post_media(title, query, out_base, caption=""):
    """Обложка и видео к одному посту. out_base — путь без расширения."""
    os.makedirs(os.path.dirname(out_base) or ".", exist_ok=True)
    media = {"photo": None, "video": None}

    photo_url = find_photo(query)
    raw_photo = download_media(photo_url, out_base + "_src.jpg") if photo_url else None
    try:
        media["photo"] = make_cover(title, raw_photo, out_base + ".jpg", caption)
    except Exception as e:
        print(f"[media] Обложка не собрана: {e}")

    video_url = find_video(query)
    raw_clip = download_media(video_url, out_base + "_src.mp4") if video_url else None
    if raw_clip:
        media["video"] = make_video(title, raw_clip, out_base + ".mp4", caption)

    for tmp in (raw_photo, raw_clip):
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    return media
