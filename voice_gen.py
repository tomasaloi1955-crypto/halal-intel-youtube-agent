# voice_gen.py — ElevenLabs для Shorts, файл для длинных
import re
import requests
import os
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
from paths import dpath
HUMAN_VOICE_DIR = dpath("my_voice")  # папка куда Фрея кладёт свои записи


def clean_for_tts(text):
    """Готовит текст к синтезу: убирает режиссёрские пометки, чтобы голос их НЕ проговаривал.
    Иначе ElevenLabs читает вслух «пауза», «[ИНТРО]» и т.п."""
    if not text:
        return text
    # пометки в квадратных/фигурных скобках: [ПАУЗА], [ИНТРО], {...}
    text = re.sub(r"[\[\{][^\]\}]*[\]\}]", " ", text)
    # скобочные ремарки-подсказки: (пауза), (pause), (вздох), (смех)
    text = re.sub(r"\(\s*(?:пауза|pause|вздох|смех|интро|интонация)[^)]*\)", " ", text, flags=re.IGNORECASE)
    # отдельно стоящие слова-ремарки «пауза» / «pause»
    text = re.sub(r"(?<![а-яёa-zА-ЯЁA-Z])(?:пауза|pause)(?![а-яёa-zА-ЯЁA-Z])", " ", text, flags=re.IGNORECASE)
    # markdown-разметка
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?m)^\s*[\*\-•]\s+", "", text)
    # схлопнуть лишние пробелы/переносы
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def generate_voice_elevenlabs(text, output_path):
    """ElevenLabs для Shorts."""
    text = clean_for_tts(text)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.3,
            "use_speaker_boost": True,
        },
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(response.content)
        print(f"[VOICE] ElevenLabs → {output_path}")
        return output_path
    except Exception as e:
        print(f"[VOICE] ElevenLabs ошибка: {e}")
        return None


def get_human_voice(slug):
    """
    Для длинных видео — ищем файл озвучки от Freya.
    Freya кладёт MP3 в папку my_voice/ с именем slug.mp3
    Например: my_voice/anthropic_965b_long.mp3
    """
    os.makedirs(HUMAN_VOICE_DIR, exist_ok=True)

    # Ищем файл по slug
    for ext in ["mp3", "ogg", "wav", "m4a"]:
        path = os.path.join(HUMAN_VOICE_DIR, f"{slug}.{ext}")
        if os.path.exists(path):
            print(f"[VOICE] Найдена твоя озвучка: {path}")
            return path

    # Ищем любой новый файл в папке (последний добавленный)
    files = []
    for ext in ["mp3", "ogg", "wav", "m4a"]:
        import glob
        files.extend(glob.glob(os.path.join(HUMAN_VOICE_DIR, f"*.{ext}")))

    if files:
        latest = max(files, key=os.path.getmtime)
        print(f"[VOICE] Используем последнюю запись: {latest}")
        return latest

    print(f"[VOICE] Нет файла озвучки в папке {HUMAN_VOICE_DIR}/")
    print(f"[VOICE] Положи MP3 туда и перезапусти агента.")
    return None


def generate_voice(text, output_path, is_shorts=True, slug=""):
    """
    Shorts → ElevenLabs автоматически.
    Длинное → ищем твою запись в папке my_voice/
    """
    if is_shorts:
        return generate_voice_elevenlabs(text, output_path)
    else:
        return get_human_voice(slug)
