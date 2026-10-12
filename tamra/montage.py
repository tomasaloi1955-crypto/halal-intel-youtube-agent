# montage.py — монтаж ролика «День N» из сырых клипов/фото и озвучки (ffmpeg + Pillow).
#
# Три шага:
#   1. Каждый клип/фото → вертикальный сегмент 1080×1920 без звука. Длина ролика = длина
#      озвучки, и она делится между клипами поровну; короткий клип отдаёт свой «излишек»
#      остальным, чтобы не крутить одну и ту же секунду по кругу.
#   2. Сегменты склеиваются без перекодирования (concat demuxer).
#   3. Поверх — PNG-накладки, нарисованные Pillow (так кириллица не ломает фильтр drawtext):
#      плашка «ДЕНЬ N» на всё видео, крупный хук первые секунды, субтитры по фразам,
#      призыв в конце. Звук — только голос (без музыки), выровненный по громкости.
#
# Обложка — кадр из готового ролика на 1-й секунде: на нём уже есть хук и плашка дня,
# поэтому в сетке профиля все ролики выглядят одинаково. Instagram берёт её же (thumb_offset).
import os
import subprocess
from PIL import Image, ImageDraw, ImageFont

from tamra import brand

W, H, FPS = brand.W, brand.H, brand.FPS
HOOK_SECONDS = 2.8
END_SECONDS = 2.2
COVER_AT = 1.0
TG_VIDEO_LIMIT = 48 * 1024 * 1024  # Telegram отдаёт ботом до 50 МБ — с запасом
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _font(size):
    for p in brand._FONT_FILES:
        path = p if os.path.isabs(p) else os.path.join(_ROOT, p)
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _run(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg: {r.stderr[-600:]}")
    return r


def duration(path):
    """Длина медиа в секундах (0 — если не удалось прочитать)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=60)
        return float(out.stdout.strip())
    except Exception:
        return 0.0


# ── раскладка по времени ───────────────────────────────────────────────────

def allocate(lengths, total):
    """Делит total секунд между клипами: поровну, но не больше длины клипа.
    lengths: None — фото (может стоять сколько угодно). Возвращает список длительностей."""
    n = len(lengths)
    out = [0.0] * n
    remaining = total
    order = sorted(range(n), key=lambda i: float("inf") if lengths[i] is None else lengths[i])
    for k, i in enumerate(order):
        share = remaining / (n - k)
        take = share if lengths[i] is None else min(lengths[i], share)
        out[i] = take
        remaining -= take
    return out


def phrase_chunks(words, max_chars=24, max_words=4):
    """Слова с таймингами [{text,start,end}] → короткие фразы для субтитров."""
    chunks, cur = [], []

    def flush():
        if cur:
            chunks.append({"text": " ".join(w["text"] for w in cur),
                           "start": cur[0]["start"], "end": cur[-1]["end"]})
            cur.clear()

    for w in words:
        t = w["text"].strip()
        if not t:
            continue
        if cur and (len(" ".join(x["text"] for x in cur)) + 1 + len(t) > max_chars
                    or len(cur) >= max_words):
            flush()
        cur.append({"text": t, "start": w["start"], "end": w["end"]})
        if t[-1] in ".,!?;:…":
            flush()
    flush()
    return chunks


def clean_subs(subs, total):
    """Нормализует субтитры: по порядку, в пределах ролика, без наложений."""
    out = []
    for s in sorted((s for s in subs if s.get("text")), key=lambda s: float(s.get("start", 0))):
        a = max(0.0, float(s.get("start", 0)))
        b = min(total, float(s.get("end", a + 1.2)))
        if out and a < out[-1]["end"]:
            out[-1]["end"] = a
            if out[-1]["end"] - out[-1]["start"] < 0.15:
                out.pop()
        if b - a >= 0.15:
            out.append({"text": str(s["text"]).strip(), "start": a, "end": b})
    return out


# ── PNG-накладки ───────────────────────────────────────────────────────────

def _wrap(d, text, f, max_w):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            test = (cur + " " + word).strip()
            if d.textlength(test, font=f) <= max_w or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return [ln for ln in lines if ln]


def _fit(d, text, max_w, max_h, sizes):
    for s in sizes:
        f = _font(s)
        lines = _wrap(d, text, f, max_w)
        if len(lines) * s * 1.18 <= max_h:
            return f, lines, s
    f = _font(sizes[-1])
    return f, _wrap(d, text, f, max_w), sizes[-1]


def _blank():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def _text_block(img, text, cy, max_w, max_h, sizes, fill=brand.CREAM, stroke=8):
    d = ImageDraw.Draw(img)
    f, lines, s = _fit(d, text, max_w, max_h, sizes)
    lh = s * 1.18
    y = cy - len(lines) * lh / 2
    for ln in lines:
        x = (W - d.textlength(ln, font=f)) / 2
        d.text((x, y), ln, font=f, fill=fill, stroke_width=stroke, stroke_fill=brand.INK)
        y += lh


def draw_badge(day, path):
    """Плашка на всё видео: «ДЕНЬ N» слева сверху, название школы справа."""
    img = _blank()
    d = ImageDraw.Draw(img)
    f = _font(46)
    label = f"ДЕНЬ {day}"
    tw = d.textlength(label, font=f)
    x0, y0 = 60, 150
    d.rounded_rectangle((x0, y0, x0 + tw + 64, y0 + 86), radius=43, fill=brand.GOLD + (255,))
    d.text((x0 + 32, y0 + 14), label, font=f, fill=brand.EMERALD_DARK)
    fb = _font(34)
    bw = d.textlength(brand.BRAND_NAME, font=fb)
    d.text((W - 60 - bw, y0 + 24), brand.BRAND_NAME, font=fb, fill=brand.CREAM,
           stroke_width=5, stroke_fill=brand.INK)
    img.save(path)


def draw_hook(text, path):
    """Крупный хук на первые секунды — он же лицо обложки."""
    img = _blank()
    shade = Image.new("RGBA", (W, 760), brand.EMERALD_DARK + (0,))
    sd = ImageDraw.Draw(shade)
    for y in range(760):  # мягкая вуаль: гуще в центре плашки, к краям прозрачнее
        a = int(170 * (1 - abs(y - 380) / 380) ** 0.6)
        sd.line([(0, y), (W, y)], fill=brand.EMERALD_DARK + (a,))
    img.alpha_composite(shade, (0, 380))
    _text_block(img, text.upper(), 760, W - 140, 560, [110, 96, 84, 72, 62], stroke=6)
    img.save(path)


def draw_sub(text, path):
    img = _blank()
    _text_block(img, text, 1440, W - 160, 300, [68, 60, 54], stroke=7)
    img.save(path)


def draw_end(path):
    img = _blank()
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((90, 1180, W - 90, 1480), radius=40, fill=brand.EMERALD + (235,),
                        outline=brand.GOLD + (255,), width=6)
    _text_block(img, brand.CTA_END, 1330, W - 260, 240, [62, 54, 48], fill=brand.CREAM, stroke=0)
    img.save(path)


# ── монтаж ─────────────────────────────────────────────────────────────────

def _segment(src, kind, seconds, out):
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"setsar=1,fps={FPS},format=yuv420p")
    if kind == "photo":
        # лёгкий наезд камеры, чтобы фото не стояло мёртвым кадром
        frames = max(1, int(seconds * FPS))
        vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
              f"zoompan=z='1+0.06*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps={FPS},setsar=1,format=yuv420p")
        inp = ["-loop", "1", "-i", src]
    else:
        inp = ["-stream_loop", "-1", "-i", src]
    _run(["ffmpeg", "-y", *inp, "-t", f"{seconds:.3f}", "-vf", vf, "-an",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), out])


def build(media, voice_path, day, hook, subs, workdir, out_path):
    """
    media: [{"path", "kind": "video"|"photo"}] в порядке присылки.
    voice_path: озвучка или None (тогда ролик немой, длина — по клипам, до 30 с).
    subs: [{"text","start","end"}] — субтитры в секундах (можно пустой список).
    Возвращает (путь к mp4, путь к обложке jpg).
    """
    os.makedirs(workdir, exist_ok=True)
    if not media:
        raise ValueError("нет ни одного клипа или фото")

    lengths = [None if m["kind"] == "photo" else (duration(m["path"]) or None) for m in media]
    if voice_path:
        total = duration(voice_path) + 0.4
    else:
        total = min(30.0, sum(3.0 if x is None else x for x in lengths))
    total = max(total, HOOK_SECONDS + END_SECONDS)

    # 1. сегменты
    slots = allocate(lengths, total)
    segs = []
    for i, (m, sec) in enumerate(zip(media, slots)):
        if sec < 0.05:
            continue
        seg = os.path.join(workdir, f"seg_{i:02d}.mp4")
        _segment(m["path"], m["kind"], sec, seg)
        segs.append(seg)

    # 2. склейка
    lst = os.path.join(workdir, "segments.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.writelines(f"file '{os.path.abspath(s)}'\n" for s in segs)
    montage = os.path.join(workdir, "montage.mp4")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", montage])

    # 3. накладки
    overlays = []  # (png, start, end)
    badge = os.path.join(workdir, "badge.png")
    draw_badge(day, badge)
    overlays.append((badge, 0, total))
    if hook:
        hp = os.path.join(workdir, "hook.png")
        draw_hook(hook, hp)
        overlays.append((hp, 0, HOOK_SECONDS))
    for i, s in enumerate(clean_subs(subs or [], total - END_SECONDS)):
        sp = os.path.join(workdir, f"sub_{i:03d}.png")
        draw_sub(s["text"], sp)
        overlays.append((sp, max(s["start"], HOOK_SECONDS if hook else 0), s["end"]))
    ep = os.path.join(workdir, "end.png")
    draw_end(ep)
    overlays.append((ep, total - END_SECONDS, total))
    overlays = [o for o in overlays if o[2] - o[1] >= 0.1]

    # длинный список фильтров — в файл, чтобы не упереться в лимит командной строки
    inputs = ["-stream_loop", "-1", "-i", montage]
    if voice_path:
        inputs += ["-i", voice_path]
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    chain, prev = [], "0:v"
    for k, (png, a, b) in enumerate(overlays):
        inputs += ["-i", png]
        nxt = f"v{k}"
        chain.append(f"[{prev}][{k + 2}:v]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[{nxt}]")
        prev = nxt
    audio = ("[1:a]highpass=f=80,loudnorm=I=-15:TP=-1.5:LRA=11,aresample=44100[aout]"
             if voice_path else "[1:a]anull[aout]")
    graph = os.path.join(workdir, "graph.txt")
    with open(graph, "w", encoding="utf-8") as f:
        f.write(";".join(chain + [audio]))

    def encode(crf):
        _run(["ffmpeg", "-y", *inputs, "-filter_complex_script", graph,
              "-map", f"[{prev}]", "-map", "[aout]", "-t", f"{total:.2f}",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-r", str(FPS),
              "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
              "-movflags", "+faststart", out_path], timeout=1500)

    encode(21)
    if os.path.getsize(out_path) > TG_VIDEO_LIMIT:
        encode(27)  # иначе бот не сможет прислать превью

    cover = os.path.splitext(out_path)[0] + "_cover.jpg"
    _run(["ffmpeg", "-y", "-ss", f"{COVER_AT:.2f}", "-i", out_path,
          "-frames:v", "1", "-q:v", "2", cover])
    return out_path, cover


if __name__ == "__main__":
    # Локальная проверка: python -m tamra.montage клип1.mp4 фото.jpg ... [--voice голос.ogg]
    import sys
    args = sys.argv[1:]
    voice = None
    if "--voice" in args:
        i = args.index("--voice")
        voice = args[i + 1]
        args = args[:i] + args[i + 2:]
    media = [{"path": p, "kind": "photo" if p.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
              else "video"} for p in args]
    print(build(media, voice, 1, "Тестовый хук ролика", [], "output/tamra_test", "output/tamra_test.mp4"))
