# shorts_timing.py — раскладывает кадры Shorts по времени ровно под голос диктора.
#
# ElevenLabs умеет вернуть вместе со звуком посимвольную разметку (endpoint
# /with-timestamps): для каждого символа известно, в какую секунду он произносится.
# На арабском канале именно это даёт эффект «картинка меняется точно в такт словам».
#
# Здесь мы не ищем слова в разметке (это хрупко), а собираем озвучиваемый текст САМИ
# из реплик сцен — значит границы каждой сцены в символах известны точно, и ошибиться
# в сопоставлении невозможно.
from voice_gen import clean_for_tts

MIN_SCENE = 1.1   # короче — кадр мелькает и не читается
TAIL = 0.7        # хвост после конца речи, чтобы последний кадр успели прочесть

# Сколько кадр держится минимально — зависит от того, сколько с него надо СЧИТАТЬ.
# Промпт зритель переписывает или фотографирует, три шага читает глазами, из двух
# вариантов выбирает — этим кадрам мало времени диктора, им нужен запас. Иначе
# главный кадр рубрики мелькает за две секунды и весь смысл ролика теряется.
MIN_BY_KIND = {"prompt": 4.5, "steps": 2.6, "choice": 3.2, "verdict": 2.4}


def _min_for(scene):
    return MIN_BY_KIND.get((scene or {}).get("kind"), MIN_SCENE)


def build_narration(scenes):
    """Склеивает реплики сцен в один текст для озвучки.

    Возвращает (текст, spans), где spans[i] — (первый символ, последний+1) i-й сцены.
    Сцены без реплики допустимы: им достанется нулевой интервал, и длительность
    будет добита до минимума в scene_spans()."""
    parts, spans, pos = [], [], 0
    for sc in scenes:
        say = clean_for_tts(sc.get("say", "") or "").strip()
        if parts and say:
            parts.append(" ")
            pos += 1
        spans.append((pos, pos + len(say)))
        if say:
            parts.append(say)
            pos += len(say)
    return "".join(parts), spans


def _from_alignment(alignment, spans):
    """Момент начала каждой сцены по посимвольной разметке ElevenLabs."""
    starts = alignment.get("character_start_times_seconds") or []
    if not starts:
        return None
    n = len(starts)
    out = []
    for a, b in spans:
        out.append(starts[min(a, n - 1)] if b > a else None)
    return out


def _from_text_length(spans, total):
    """Резерв, если разметки нет: делим время пропорционально длине реплик."""
    lengths = [max(1, b - a) for a, b in spans]
    whole = sum(lengths)
    out, acc = [], 0.0
    for ln in lengths:
        out.append(acc)
        acc += total * ln / whole
    return out


def scene_spans(scenes, audio_duration, alignment=None):
    """[(начало, длительность)] для каждой сцены — в сумме вся длина ролика.

    Правим три вещи: пропуски у сцен без реплики, кадры короче MIN_SCENE и
    выход за длину аудио. Иначе нейросеть, выдав пустую реплику, ломает монтаж."""
    _, spans = build_narration(scenes)
    total = audio_duration + TAIL
    starts = _from_alignment(alignment, spans) if alignment else None
    if starts is None or all(s is None for s in starts):
        starts = _from_text_length(spans, audio_duration)

    # пропуски (сцена без реплики) заполняем между соседями
    for i, s in enumerate(starts):
        if s is None:
            prev = next((starts[j] for j in range(i - 1, -1, -1) if starts[j] is not None), 0.0)
            nxt = next((starts[j] for j in range(i + 1, len(starts)) if starts[j] is not None), total)
            starts[i] = (prev + nxt) / 2

    n = len(starts)
    starts[0] = 0.0
    mins = [_min_for(s) for s in scenes]
    # монотонность + минимальная длительность кадра.
    # Кадр может пережить свою реплику и залезть на следующую: озвучка от этого не
    # съезжает (звук идёт сплошняком), а прочесть промпт зритель успевает.
    for i in range(1, n):
        starts[i] = max(starts[i], starts[i - 1] + mins[i - 1])
    # если из-за минимумов уехали за конец — раздаём время пропорционально минимумам
    if starts[-1] + mins[-1] > total:
        whole = sum(mins)
        acc = 0.0
        for i in range(n):
            starts[i] = acc
            acc += total * mins[i] / whole

    out = []
    for i in range(n):
        end = starts[i + 1] if i + 1 < n else total
        out.append((round(starts[i], 3), round(max(0.5, end - starts[i]), 3)))
    return out
