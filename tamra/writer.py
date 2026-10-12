# writer.py — тексты к ролику: хук на экран, заголовок YouTube, подпись, хэштеги, субтитры.
#
# Нейросеть (Gemini) слушает саму озвучку + заметку, которую ты прислала боту, и пишет
# тексты только из них и из фактов о школе (brand.SCHOOL_FACTS) — ничего не додумывая.
# Субтитры с точными таймингами даёт ElevenLabs Speech-to-Text (если есть ключ);
# без него — тайминги фраз от Gemini, они грубее, но лучше, чем ничего.
# Нейросеть недоступна — ролик всё равно собирается: хук и подпись из твоей заметки.
import os
import json
import time
import requests

from tamra import brand
from tamra.montage import phrase_chunks

GEMINI_MODEL = "gemini-2.5-flash"
_MIME = {"ogg": "audio/ogg", "oga": "audio/ogg", "mp3": "audio/mpeg", "m4a": "audio/mp4",
         "wav": "audio/wav", "mp4": "audio/mp4", "aac": "audio/aac"}


def _prompt(day, notes, with_audio, need_subs):
    note = "\n".join(notes).strip() or "(заметки нет)"
    subs = ('"subtitles": [{"text": "2-4 слова", "start": 0.0, "end": 1.2}, ...]  '
            "— дословная расшифровка озвучки короткими фразами, время в секундах от начала записи,"
            if need_subs else "")
    return f"""Ты — SMM-редактор канала школы. Ниже факты о школе, заметка автора и (если приложена)
её озвучка к ролику «День {day}» — ежедневный дневник создания школы, канал без лица.

ФАКТЫ О ШКОЛЕ (используй только их, ничего не выдумывай — цифр, отзывов, результатов учеников):
{brand.SCHOOL_FACTS}

ЗАМЕТКА АВТОРА: {note}
{"ОЗВУЧКА приложена — главное содержание ролика бери из неё." if with_audio else "Озвучки нет — опирайся на заметку."}

Аудитория — мусульманские родители (чаще мамы), русскоязычные, в т.ч. живущие за границей.
Тон тёплый, уважительный, без агрессии к другим школам. Можно «Ассаляму алейкум» в подписи.
Никакой музыки и ничего, что противоречит исламу.

Верни ТОЛЬКО JSON:
{{
  "hook": "хук на экран первых секунд, 3-7 слов, цепляет родителя, без хэштегов и эмодзи",
  "title": "заголовок YouTube Shorts до 70 символов",
  "caption": "подпись для Instagram/TikTok: 2-5 коротких строк по сути ролика, вопрос к зрителям, в конце строка про бесплатный тест уровня по ссылке в профиле. Без хэштегов",
  "hashtags": ["#до", "#8", "#тематических"],
  {subs}
  "transcript": "дословный текст озвучки или пустая строка"
}}"""


def _parse(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    return json.loads(text[text.find("{"):text.rfind("}") + 1])


def _gemini(prompt, audio_path=None):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    import google.generativeai as genai
    genai.configure(api_key=key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    parts = [prompt]
    if audio_path:
        ext = audio_path.rsplit(".", 1)[-1].lower()
        f = genai.upload_file(audio_path, mime_type=_MIME.get(ext, "audio/ogg"))
        for _ in range(30):  # файл должен «дозреть» до ACTIVE, обычно это секунды
            if f.state.name != "PROCESSING":
                break
            time.sleep(2)
            f = genai.get_file(f.name)
        parts = [f, prompt]
    resp = model.generate_content(parts, generation_config={"response_mime_type": "application/json"})
    return _parse(resp.text)


def elevenlabs_words(audio_path):
    """Точные тайминги слов от ElevenLabs Speech-to-Text. None — если ключа нет или сбой."""
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key or os.getenv("TAMRA_ELEVENLABS_STT", "true").lower() in ("0", "false", "no", "off"):
        return None
    try:
        with open(audio_path, "rb") as f:
            r = requests.post("https://api.elevenlabs.io/v1/speech-to-text",
                              headers={"xi-api-key": key},
                              data={"model_id": "scribe_v1", "language_code": "rus"},
                              files={"file": (os.path.basename(audio_path), f)}, timeout=300)
        r.raise_for_status()
        words = [{"text": w["text"], "start": float(w["start"]), "end": float(w["end"])}
                 for w in r.json().get("words", [])
                 if w.get("type", "word") == "word" and w.get("text", "").strip()]
        return words or None
    except Exception as e:
        print(f"[TAMRA] ElevenLabs STT недоступен: {e}")
        return None


def _fallback(day, notes):
    note = " ".join(notes).strip()
    hook = note.split(".")[0][:60] if note else f"Строю исламскую ИИ-школу. День {day}"
    return {
        "hook": hook,
        "title": f"День {day}: строю исламскую ИИ-школу",
        "caption": (note + "\n\n" if note else "") +
                   "Бесплатный тест уровня для ребёнка — ссылка в профиле.",
        "hashtags": [],
        "subtitles": [],
    }


def write(day, notes, audio_path=None):
    """Возвращает dict: hook, title, caption, hashtags (list), subtitles ([{text,start,end}])."""
    words = elevenlabs_words(audio_path) if audio_path else None
    try:
        data = _gemini(_prompt(day, notes, bool(audio_path), need_subs=bool(audio_path) and not words),
                       audio_path) or _fallback(day, notes)
    except Exception as e:
        print(f"[TAMRA] Gemini недоступен, тексты из заметки: {e}")
        data = _fallback(day, notes)

    if words:
        data["subtitles"] = phrase_chunks(words)
    tags = [t if t.startswith("#") else "#" + t for t in data.get("hashtags", []) if t.strip()]
    for t in brand.HASHTAGS:
        if t not in tags:
            tags.append(t)
    return {
        "hook": (data.get("hook") or "").strip(),
        "title": (data.get("title") or f"День {day}: Tamra School").strip()[:90],
        "caption": (data.get("caption") or "").strip(),
        "hashtags": tags[:12],
        "subtitles": data.get("subtitles") or [],
    }


def full_caption(texts):
    return f"{texts['caption']}\n\n{' '.join(texts['hashtags'])}".strip()
