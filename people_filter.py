# people_filter.py — ЖЁСТКИЙ ЗАПРЕТ ЛЮДЕЙ В КАДРЕ (05.10.2026).
#
# ЗАЧЕМ. Стоковые фото и видео (Pexels) берутся по поисковому запросу, а запрос
# «без людей» ничего не гарантирует: в соседнем канале «Мусульманка на спорте» в пост
# попал мужчина в шортах. Поэтому каждый стоковый кадр перед тем, как попасть в
# ролик, обложку или пост, смотрит ИИ-модель (Claude vision). Есть человек или его
# часть — кадр выбрасывается.
#
# ПРАВИЛО: в сомнительном случае кадр НЕ берём. Нет ключа ANTHROPIC_API_KEY, ошибка
# API, непонятный ответ — всё это значит «кадр отклонён», а не «пропустим проверку».
import base64
import io
import os
import shutil
import subprocess

import requests
from PIL import Image

VISION_MODEL = os.getenv("VISION_MODEL", "claude-sonnet-5")

VISION_PROMPT = """Это кадр для исламского канала. Правило: на кадре НЕ ДОЛЖНО быть людей вообще.
Посмотри на {n} изображени(е/я) внимательно, включая фон, края, отражения в зеркалах и окнах,
экраны, плакаты, силуэты, тени, манекены, статуи, роботов-гуманоидов, рисунки и мультяшных персонажей.

Ответь NO_PEOPLE только если ни на одном изображении нет:
- человека или его части (лицо, рука, кисть, палец, нога, ступня, спина, тело, волосы);
- силуэта, тени или отражения человека;
- манекена, статуи, куклы, робота-гуманоида или рисунка в виде человека;
- алкоголя, свинины, крестов, казино.
Во всех остальных случаях, и если сомневаешься, ответь PEOPLE.
Ответь одним словом: NO_PEOPLE или PEOPLE."""

VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv")


def _jpeg_b64(path, max_side=768):
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def no_people(image_paths):
    """True, только если ИИ уверенно подтвердил: на всех кадрах нет людей.
    Любая ошибка или непонятный ответ — False (кадр не берём)."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        print("[PEOPLE] ANTHROPIC_API_KEY не задан — кадр нельзя проверить, не берём")
        return False
    if not image_paths:
        return False
    try:
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": _jpeg_b64(p)}} for p in image_paths]
        content.append({"type": "text", "text": VISION_PROMPT.format(n=len(image_paths))})
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": VISION_MODEL, "max_tokens": 10,
                  "messages": [{"role": "user", "content": content}]},
            timeout=60,
        )
        resp.raise_for_status()
        answer = "".join(b.get("text", "") for b in resp.json().get("content", [])).strip().upper()
        ok = answer.startswith("NO_PEOPLE")
        print(f"[PEOPLE] Проверка кадра ИИ: {answer!r} → {'берём' if ok else 'отклонён'}")
        return ok
    except Exception as e:
        print(f"[PEOPLE] Проверка кадра ИИ не удалась, кадр не берём: {e}")
        return False


def _duration(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=noprint_wrappers=1:nokey=1", path],
                             capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except Exception:
        return 8.0


def video_frames(clip_path, count=4):
    """Пути к count кадрам, равномерно взятым по всей длине клипа."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    dur = _duration(clip_path)
    base = clip_path.rsplit(".", 1)[0]
    frames = []
    for i in range(count):
        frame = f"{base}_chk{i}.jpg"
        try:
            subprocess.run([ffmpeg, "-y", "-ss", f"{dur * (i + 0.5) / count:.2f}", "-i", clip_path,
                            "-frames:v", "1", "-q:v", "3", frame], capture_output=True, timeout=60)
        except Exception as e:
            print(f"[PEOPLE] Кадр из видео не извлечён: {e}")
        if os.path.exists(frame):
            frames.append(frame)
    return frames


def media_is_clean(path):
    """Фото или видео без людей? Для видео проверяются 4 кадра по всей длине."""
    if not path or not os.path.exists(path):
        return False
    if path.lower().endswith(VIDEO_EXTS):
        frames = video_frames(path)
        try:
            return len(frames) >= 2 and no_people(frames)
        finally:
            for f in frames:
                os.remove(f)
    return no_people([path])


def keep_if_clean(path):
    """Возвращает path, если на файле нет людей; иначе удаляет файл и возвращает None."""
    if path and media_is_clean(path):
        return path
    if path and os.path.exists(path):
        os.remove(path)
    return None
