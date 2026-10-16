# writer.py — тексты к ролику: хук на экран, заголовок YouTube, подпись, хэштеги, субтитры.
#
# Нейросеть (Gemini) слушает саму озвучку + заметку, которую ты прислала боту, и пишет
# тексты только из них и из фактов о школе (brand.SCHOOL_FACTS) — ничего не додумывая.
# Субтитры с точными таймингами даёт ElevenLabs Speech-to-Text, а если его ключ не работает —
# Whisper на Groq (GROQ_API_KEY). Без обоих — тайминги фраз от Gemini, они грубее.
# Gemini недоступен — тексты пишет модель на Groq по расшифровке озвучки.
# Не работает ничего — ролик всё равно собирается: хук и подпись из твоей заметки.
import os
import json
import time
import requests

from tamra import brand
from tamra.montage import phrase_chunks

GEMINI_MODEL = "gemini-2.5-flash"
GROQ_API = "https://api.groq.com/openai/v1"
GROQ_TEXT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_STT_MODEL = "whisper-large-v3-turbo"
_MIME = {"ogg": "audio/ogg", "oga": "audio/ogg", "mp3": "audio/mpeg", "m4a": "audio/mp4",
         "wav": "audio/wav", "mp4": "audio/mp4", "aac": "audio/aac"}


def _prompt(day, notes, with_audio, need_subs, transcript=""):
    note = "\n".join(notes).strip() or "(заметки нет)"
    if with_audio:
        source = "ОЗВУЧКА приложена — главное содержание ролика бери из неё."
    elif transcript:
        source = f"РАСШИФРОВКА ОЗВУЧКИ (главное содержание ролика): {transcript}"
    else:
        source = "Озвучки нет — опирайся на заметку."
    subs = ('"subtitles": [{"text": "2-4 слова", "start": 0.0, "end": 1.2}, ...]  '
            "— дословная расшифровка озвучки короткими фразами, время в секундах от начала записи,"
            if need_subs else "")
    return f"""Ты — SMM-редактор канала школы. Ниже факты о школе, заметка автора и (если приложена)
её озвучка к ролику «День {day}» — ежедневный дневник создания школы, канал без лица.

ФАКТЫ О ШКОЛЕ (используй только их, ничего не выдумывай — цифр, отзывов, результатов учеников):
{brand.SCHOOL_FACTS}

ЗАМЕТКА АВТОРА: {note}
{source}

Аудитория — мусульманские родители (чаще мамы), русскоязычные, в т.ч. живущие за границей.
Тон тёплый, уважительный, без агрессии к другим школам. Можно «Ассаляму алейкум» в подписи.
Название школы пиши всегда латиницей: Tamra School (не «Тамра Скул», даже если так в расшифровке).
Никакой музыки и ничего, что противоречит исламу.

Верни ТОЛЬКО JSON:
{{
  "hook": "хук на экран первых секунд, 3-7 слов, цепляет родителя, без хэштегов и эмодзи",
  "title": "заголовок YouTube Shorts до 70 символов",
  "caption": "подпись для Instagram/TikTok: 2-5 коротких строк по сути ролика, вопрос к зрителям, в конце строка про бесплатный тест уровня по ссылке в профиле. Без хэштегов",
  "hashtags": ["#до", "#5", "#нейтральных", "#про_образование_и_семью"],
  "stock_queries": ["3-5 коротких запросов НА АНГЛИЙСКОМ для стоковых видео под содержание озвучки, по порядку рассказа: предметы и руки, без лиц — например countdown timer, child hands laptop, quran stand, hourglass"],
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


def groq_words(audio_path):
    """Тайминги слов от Whisper на Groq. None — если ключа нет или сбой."""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    try:
        with open(audio_path, "rb") as f:
            r = requests.post(f"{GROQ_API}/audio/transcriptions",
                              headers={"Authorization": f"Bearer {key}"},
                              data={"model": GROQ_STT_MODEL, "language": "ru",
                                    "response_format": "verbose_json",
                                    "timestamp_granularities[]": "word"},
                              files={"file": (os.path.basename(audio_path), f)}, timeout=300)
        r.raise_for_status()
        words = [{"text": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
                 for w in r.json().get("words", []) if w.get("word", "").strip()]
        return words or None
    except Exception as e:
        print(f"[TAMRA] Groq Whisper недоступен: {e}")
        return None


def _groq(prompt):
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    r = requests.post(f"{GROQ_API}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                      json={"model": GROQ_TEXT_MODEL, "temperature": 0.7,
                            "messages": [{"role": "user", "content": prompt}]}, timeout=120)
    r.raise_for_status()
    return _parse(r.json()["choices"][0]["message"]["content"])


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
    notes = [n for n in notes if not n.strip().startswith("/")]  # случайные команды — не заметки
    words = (elevenlabs_words(audio_path) or groq_words(audio_path)) if audio_path else None
    transcript = " ".join(w["text"] for w in words) if words else ""
    data = None
    try:
        data = _gemini(_prompt(day, notes, bool(audio_path), need_subs=bool(audio_path) and not words),
                       audio_path)
    except Exception as e:
        print(f"[TAMRA] Gemini недоступен, пробую Groq: {e}")
    if not data:
        try:
            data = _groq(_prompt(day, notes, False, need_subs=False, transcript=transcript))
        except Exception as e:
            print(f"[TAMRA] Groq недоступен, тексты из заметки: {e}")
    data = data or _fallback(day, notes)

    if words:
        data["subtitles"] = phrase_chunks(words)
    tags = [t if t.startswith("#") else "#" + t for t in data.get("hashtags", [])
            if t.strip() and not any(w in t.lower() for w in _BLOCKED_TAG_WORDS)]
    for t in brand.HASHTAGS:
        if t not in tags:
            tags.append(t)
    return {
        "hook": _fix_name(data.get("hook")).strip(),
        "title": _fix_name(data.get("title") or f"День {day}: Tamra School").strip()[:90],
        "caption": _fix_name(data.get("caption")).strip(),
        "hashtags": tags[:12],
        "subtitles": data.get("subtitles") or [],
        "stock_queries": [q.strip() for q in data.get("stock_queries", [])
                          if isinstance(q, str) and q.strip()][:5],
    }


# Нейросеть иногда добавляет политически окрашенные теги — такие не ставим никогда
_BLOCKED_TAG_WORDS = ("движени", "джихад", "халифат", "умма", "политик", "война", "борьб")


def _fix_name(text):
    """Расшифровка голоса пишет «Тамра Скул» — в текстах всегда фирменное «Tamra School»."""
    import re
    return re.sub(r"[ТтTt]амр[аеу]\s*[Сс]ку[лл]\w*", "Tamra School", text or "")


def full_caption(texts):
    return f"{texts['caption']}\n\n{' '.join(texts['hashtags'])}".strip()
