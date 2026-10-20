# rawcut.py — «сырой ролик»: видео со своим голосом → без пауз и «эээ», при нужде ускорено.
#
# Когда ты присылаешь видео без отдельной озвучки, а в видео есть звук — это и есть озвучка.
#   1. Все присланные видео приводятся к 1080×1920 и склеиваются вместе со звуком.
#   2. Тишина ищется ffmpeg silencedetect: паузы длиннее MIN_PAUSE вырезаются, от каждой
#      остаётся KEEP_PAUSE с краёв — речь не звучит рублено.
#   3. Слова-паразиты («э», «ээ», «мм», «эм») ищутся по таймингам слов из распознавания речи
#      (writer.elevenlabs_words / groq_words) и вырезаются так же, как паузы.
#   4. Если без пауз ролик длиннее TARGET_SECONDS — ускоряем, но не больше MAX_SPEED: дальше
#      голос звучит неестественно. Ролик длиннее минуты всё равно уйдёт в Shorts (до 3 минут).
#
# Что вырезать, считается один раз и сохраняется в черновике (cut): пересборка перед
# публикацией режет ровно так же, без повторного распознавания.
import os
import re
import subprocess

from tamra import brand

NOISE_DB = -35        # тише этого — тишина
MIN_PAUSE = 0.45      # паузы короче — естественные, не трогаем
KEEP_PAUSE = 0.12     # сколько тишины оставить с каждой стороны вырезанной паузы
TARGET_SECONDS = 58
MAX_SPEED = 1.25
FILLERS = {"э", "ээ", "эээ", "эм", "эмм", "мм", "ммм", "хм", "а-а", "ммм-м", "uh", "um", "эх"}


def _run(cmd, timeout=1500):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg: {r.stderr[-500:]}")
    return r


def has_audio(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                          "stream=index", "-of", "csv=p=0", path],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    return bool(out)


def _duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=60)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def join(paths, out):
    """Склейка присланных видео в один вертикальный ролик со звуком."""
    W, H, FPS = brand.W, brand.H, brand.FPS
    inputs, chains = [], []
    for i, p in enumerate(paths):
        inputs += ["-i", p]
        chains.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                      f"setsar=1,fps={FPS},format=yuv420p[v{i}]")
        if has_audio(p):
            chains.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
        else:  # немой клип посередине — тишина той же длины, чтобы звук не съехал
            chains.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{_duration(p):.3f}[a{i}]")
    pairs = "".join(f"[v{i}][a{i}]" for i in range(len(paths)))
    graph = ";".join(chains) + f";{pairs}concat=n={len(paths)}:v=1:a=1[v][a]"
    _run(["ffmpeg", "-y", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k", out])
    return out


def silences(path):
    r = subprocess.run(["ffmpeg", "-i", path, "-af", f"silencedetect=noise={NOISE_DB}dB:d={MIN_PAUSE}",
                        "-f", "null", "-"], capture_output=True, text=True, timeout=600)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    total = _duration(path)
    return [(a, ends[i] if i < len(ends) else total) for i, a in enumerate(starts)]


def filler_spans(words):
    return [(w["start"], w["end"]) for w in words or []
            if re.sub(r"[^\wа-яё-]", "", w["text"].lower()) in FILLERS]


def keep_segments(total, cuts):
    """Что оставить: всё, кроме вырезов (у пауз остаётся KEEP_PAUSE с краёв)."""
    cuts = sorted((max(0.0, a), min(total, b)) for a, b in cuts if b > a)
    keep, pos = [], 0.0
    for a, b in cuts:
        a2, b2 = a + KEEP_PAUSE, b - KEEP_PAUSE
        if b2 - a2 <= 0.05:
            continue
        if a2 > pos:
            keep.append((pos, a2))
        pos = max(pos, b2)
    if total > pos:
        keep.append((pos, total))
    return [(round(a, 3), round(b, 3)) for a, b in keep if b - a > 0.08]


def plan(joined, words=None):
    """Что вырезать и с какой скоростью — сохраняется в черновике."""
    total = _duration(joined)
    keep = keep_segments(total, silences(joined) + filler_spans(words))
    kept = sum(b - a for a, b in keep) or total
    speed = round(min(MAX_SPEED, kept / TARGET_SECONDS), 3) if kept > TARGET_SECONDS else 1.0
    return {"keep": keep or [(0.0, total)], "speed": speed, "orig": round(total, 1),
            "final": round(kept / speed, 1)}


def apply(joined, cut, video_out, audio_out, workdir):
    """Режет склейку по плану: видео без звука (для монтажа) и звук отдельно (озвучка)."""
    sel = "+".join(f"between(t,{a},{b})" for a, b in cut["keep"])
    sp = cut["speed"]
    script = os.path.join(workdir, "rawcut.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write(f"[0:v]select='{sel}',setpts=(N/FRAME_RATE/TB)/{sp}[v];"
                f"[0:a]aselect='{sel}',asetpts=N/SR/TB,atempo={sp}[a]")
    _run(["ffmpeg", "-y", "-i", joined, "-filter_complex_script", script,
          "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
          "-r", str(brand.FPS), video_out,
          "-map", "[a]", "-vn", "-c:a", "pcm_s16le", "-ar", "48000", audio_out])
    return video_out, audio_out
