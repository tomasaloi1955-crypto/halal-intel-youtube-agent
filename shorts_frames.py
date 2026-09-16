# shorts_frames.py — фирменные кадры вертикальных Shorts (720×1280), рисуются Pillow.
#
# ЗАЧЕМ. До этого видеоряд Shorts был случайным стоком с Pexels («humanoid robot»,
# «data center»): красиво, но к словам диктора отношения не имеет — зритель не
# получает из картинки НИЧЕГО и пролистывает. На арабском канале сделано наоборот:
# в кадре лежит само содержание урока (слово крупно, в круге), и оно меняется
# ровно тогда, когда диктор произносит нужное слово. Именно это там и работает.
#
# Здесь тот же приём перенесён на ИИ-тематику: в кадре — сам промпт, сам шаг,
# сама цифра. Зритель может поставить на паузу и забрать это себе (сохранение —
# самый сильный сигнал для ленты Shorts, новости его не дают).
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 720, 1280

# ── палитра: тёмная база + фирменное золото канала (то же, что на обложках) ──
BG_TOP    = (16, 22, 43)
BG_BOTTOM = (8, 11, 23)
GOLD      = (246, 183, 60)
GOLD_DIM  = (150, 112, 38)
BLUE      = (46, 155, 255)
GREEN     = (72, 199, 142)
RED       = (233, 91, 84)
WHITE     = (255, 255, 255)
OFF_WHITE = (226, 230, 244)
MUTED     = (138, 148, 175)
CARD_BG   = (22, 29, 52)

BRAND_AVATAR = os.path.join("brand", "presenter_avatar.png")
TG_CHANNEL = "t.me/Halalaifreya"

_FONTS = {
    True: ["brand/fonts/Montserrat-ExtraBold.ttf", "brand/fonts/Montserrat-Bold.ttf",
           "C:/Windows/Fonts/arialbd.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    False: ["brand/fonts/Montserrat-Bold.ttf", "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}


def font(size, bold=True):
    for p in _FONTS[bold]:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ── фон (кэшируется: один и тот же для всех кадров ролика) ──────────────────

_BG_CACHE = None


def _make_bg():
    img = Image.new("RGB", (W, H), BG_BOTTOM)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(
            int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
            int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
            int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)))

    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    # сетка точек — фактура, чтобы фон не был «пустой заливкой»
    step = 46
    for x in range(step // 2, W, step):
        for y in range(step // 2, H, step):
            od.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(*GOLD, 16))
    # золотое свечение по центру
    cx, cy, max_r = W // 2, 560, 420
    for r in range(max_r, 0, -6):
        od.ellipse((cx - r, cy - r, cx + r, cy + r),
                   fill=(*GOLD, int(14 * (1 - r / max_r) ** 0.6)))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

    # уголки-скобки — узнаваемая рамка канала
    d = ImageDraw.Draw(img)
    m, sz = 44, 120
    for (x0, y0, x1, y1, x2, y2) in [
        (m, m + sz, m, m, m + sz, m),
        (W - m - sz, m, W - m, m, W - m, m + sz),
        (m, H - m - sz, m, H - m, m + sz, H - m),
        (W - m - sz, H - m, W - m, H - m, W - m, H - m - sz),
    ]:
        d.line([(x0, y0), (x1, y1), (x2, y2)], fill=GOLD_DIM, width=2)
    return img


def _bg():
    global _BG_CACHE
    if _BG_CACHE is None:
        _BG_CACHE = _make_bg()
    return _BG_CACHE.copy()


# ── примитивы ────────────────────────────────────────────────────────────────

def _pill(img, text, x, y, f, fill=None, outline=None, color=WHITE, pad=(22, 12)):
    d = ImageDraw.Draw(img)
    bb = d.textbbox((0, 0), text, font=f)
    pw = (bb[2] - bb[0]) + pad[0] * 2
    ph = (bb[3] - bb[1]) + pad[1] * 2
    pill = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pill)
    pd.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=ph // 2,
                         fill=fill, outline=outline, width=2)
    img.paste(pill, (x, y), pill)
    ImageDraw.Draw(img).text((x + pad[0] - bb[0], y + pad[1] - bb[1]),
                             text, font=f, fill=color)
    return pw, ph


def _wrap(d, text, f, max_w):
    """Перенос по словам под реальную ширину шрифта."""
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textlength(test, font=f) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_lines(d, text, max_w, max_h, sizes, bold=True, line_ratio=1.22):
    """Подбирает самый крупный кегль, при котором текст влезает в блок.

    Кегль НЕ фиксированный: сценарий пишет нейросеть, длина фразы гуляет, и
    жёсткий кегль либо режет текст, либо оставляет полупустой кадр."""
    for s in sizes:
        f = font(s, bold)
        lines = _wrap(d, text, f, max_w)
        lh = int(s * line_ratio)
        if len(lines) * lh <= max_h:
            return f, lines, lh
    f = font(sizes[-1], bold)
    return f, _wrap(d, text, f, max_w), int(sizes[-1] * line_ratio)


def _draw_block(img, text, cy, max_w=W - 120, max_h=460,
                sizes=(66, 58, 50, 44, 38, 32), color=WHITE, bold=True, shadow=True):
    """Текстовый блок, центрированный относительно cy."""
    d = ImageDraw.Draw(img)
    f, lines, lh = _fit_lines(d, text, max_w, max_h, sizes, bold)
    y = cy - len(lines) * lh // 2
    for ln in lines:
        lw = d.textlength(ln, font=f)
        x = (W - lw) / 2
        if shadow:
            d.text((x + 2, y + 3), ln, font=f, fill=(0, 0, 0))
        d.text((x, y), ln, font=f, fill=color)
        y += lh
    return y


def _chrome(img, rubric, episode):
    """Верхние бейджи (рубрика + номер выпуска) и нижняя плашка Telegram.

    Номер выпуска — не украшение: он превращает ролики в сериал, а сериал даёт
    повод вернуться завтра. На арабском канале это работает именно так."""
    f_small = font(21)
    _pill(img, (rubric or "").upper(), 44, 58, f_small,
          fill=(*GOLD, 28), outline=(*GOLD, 150), color=GOLD)
    if episode:
        ep = "#%s" % episode
        d = ImageDraw.Draw(img)
        bb = d.textbbox((0, 0), ep, font=f_small)
        pw = (bb[2] - bb[0]) + 36
        _pill(img, ep, W - 44 - pw, 58, f_small, fill=GOLD, color=(16, 20, 34))

    f_tg = font(26, bold=False)
    d = ImageDraw.Draw(img)
    tw = d.textlength(TG_CHANNEL, font=f_tg)
    _pill(img, TG_CHANNEL, int((W - tw - 44) / 2), H - 96, f_tg,
          fill=(0, 0, 0, 150), color=OFF_WHITE, pad=(22, 10))


def _avatar(img, height=250):
    """Ведущая в углу — единственный узнаваемый знак канала без живой съёмки.
    Нет файла — просто пропускаем, кадр не ломается."""
    if not os.path.exists(BRAND_AVATAR):
        return
    try:
        av = Image.open(BRAND_AVATAR).convert("RGBA")
        k = height / av.height
        av = av.resize((max(1, int(av.width * k)), height), Image.LANCZOS)
        img.paste(av, (W - av.width - 18, H - height - 104), av)
    except Exception as e:
        print("[FRAME] Аватар не наложился: %s" % e)


def _card(img, x0, y0, x1, y1, accent=GOLD, fill=CARD_BG, radius=26):
    card = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle((0, 0, x1 - x0 - 1, y1 - y0 - 1), radius=radius,
                         fill=(*fill, 242), outline=(*accent, 110), width=2)
    cd.rounded_rectangle((0, 0, 8, y1 - y0 - 1), radius=4, fill=accent)
    img.paste(card, (x0, y0), card)


def _label(img, text, cy, color=GOLD, size=28):
    d = ImageDraw.Draw(img)
    f = font(size)
    t = (text or "").upper()
    d.text(((W - d.textlength(t, font=f)) / 2, cy), t, font=f, fill=color)


# ── сцены ────────────────────────────────────────────────────────────────────

def _scene_hook(img, data):
    _draw_block(img, data.get("text", ""), 620, max_h=520,
                sizes=(76, 66, 58, 50, 44, 38))


def _scene_text(img, data):
    if data.get("label"):
        _label(img, data["label"], 360)
    _draw_block(img, data.get("text", ""), 620, max_h=460,
                sizes=(62, 54, 48, 42, 36, 30))


def _scene_prompt(img, data):
    """Главный кадр рубрики «Промпт дня»: готовый промпт крупно — его можно
    сфотографировать или поставить на паузу и переписать."""
    _label(img, data.get("label") or "СКОПИРУЙ СЕБЕ", 300)
    x0, x1 = 48, W - 48
    y0, y1 = 350, 900
    _card(img, x0, y0, x1, y1)
    d = ImageDraw.Draw(img)
    f, lines, lh = _fit_lines(d, data.get("text", ""), x1 - x0 - 84, y1 - y0 - 80,
                              (40, 36, 32, 29, 26, 23, 20), bold=False, line_ratio=1.35)
    y = y0 + ((y1 - y0) - len(lines) * lh) // 2
    for ln in lines:
        d.text((x0 + 42, y), ln, font=f, fill=OFF_WHITE)
        y += lh
    _label(img, "СОХРАНИ, ПОКА НЕ ПОТЕРЯЛ", 930, size=30)


def _scene_steps(img, data):
    """Шаги 1-2-3. Активный шаг подсвечен — глаз ведут по кадру, а не бросают."""
    steps = data.get("steps") or []
    active = data.get("active", 0)
    _label(img, data.get("label") or "ПО ШАГАМ", 320)
    top, gap, hgt = 390, 24, 150
    d = ImageDraw.Draw(img)
    for i, st in enumerate(steps[:3]):
        y0 = top + i * (hgt + gap)
        y1 = y0 + hgt
        on = (i == active)
        _card(img, 48, y0, W - 48, y1,
              accent=GOLD if on else GOLD_DIM,
              fill=CARD_BG if on else (16, 21, 38))
        f_n = font(46)
        d.ellipse((86, y0 + 44, 148, y1 - 44), fill=GOLD if on else (44, 52, 78))
        n = str(i + 1)
        d.text((86 + (62 - d.textlength(n, font=f_n)) / 2, y0 + 46),
               n, font=f_n, fill=(16, 20, 34) if on else MUTED)
        f_t, lines, lh = _fit_lines(d, st, W - 96 - 150, hgt - 40,
                                    (36, 32, 28, 25, 22), bold=on)
        ty = y0 + (hgt - len(lines) * lh) // 2
        for ln in lines:
            d.text((176, ty), ln, font=f_t, fill=WHITE if on else MUTED)
            ty += lh


def _scene_number(img, data):
    """Вау-цифра во весь кадр. Новость запоминается числом, а не пересказом."""
    _label(img, data.get("label") or "", 330)
    d = ImageDraw.Draw(img)
    num = str(data.get("number", ""))
    f, lines, lh = _fit_lines(d, num, W - 120, 260, (190, 160, 130, 108, 90, 74))
    y = 400
    for ln in lines:
        lw = d.textlength(ln, font=f)
        d.text(((W - lw) / 2 + 3, y + 4), ln, font=f, fill=(0, 0, 0))
        d.text(((W - lw) / 2, y), ln, font=f, fill=GOLD)
        y += lh
    _draw_block(img, data.get("text", ""), y + 150, max_h=280,
                sizes=(52, 46, 40, 34, 30))


VERDICT_COLORS = {"халяль": GREEN, "харам": RED}


def _scene_verdict(img, data):
    verdict = (data.get("verdict") or "").strip()
    color = VERDICT_COLORS.get(verdict.lower(), GOLD)
    f = font(58)
    d = ImageDraw.Draw(img)
    t = verdict.upper()
    bb = d.textbbox((0, 0), t, font=f)
    pw = (bb[2] - bb[0]) + 72
    _pill(img, t, int((W - pw) / 2), 380, f, fill=(*color, 40),
          outline=color, color=color, pad=(36, 20))
    _draw_block(img, data.get("text", ""), 760, max_h=340,
                sizes=(50, 44, 38, 33, 28), color=OFF_WHITE)


def _scene_choice(img, data):
    """Выбор А/Б в конце — двигатель комментариев: ответить одной буквой легко."""
    _label(img, data.get("label") or "А ТЫ КАК СЧИТАЕШЬ?", 330)
    d = ImageDraw.Draw(img)
    opts = data.get("options") or []
    top, hgt, gap = 400, 170, 28
    for i, (letter, txt) in enumerate(zip(("А", "Б"), opts[:2])):
        y0 = top + i * (hgt + gap)
        _card(img, 48, y0, W - 48, y0 + hgt, accent=GOLD if i == 0 else BLUE)
        f_l = font(60)
        d.text((92, y0 + (hgt - 76) / 2), letter, font=f_l,
               fill=GOLD if i == 0 else BLUE)
        f_t, lines, lh = _fit_lines(d, txt, W - 96 - 160, hgt - 40,
                                    (38, 34, 30, 26, 23))
        ty = y0 + (hgt - len(lines) * lh) // 2
        for ln in lines:
            d.text((184, ty), ln, font=f_t, fill=WHITE)
            ty += lh
    _label(img, "ПИШИ БУКВУ В КОММЕНТАРИЯХ", 806, color=OFF_WHITE, size=30)


def _scene_cta(img, data):
    _draw_block(img, data.get("text") or "Подпишись — такой разбор каждый день",
                560, max_h=340, sizes=(60, 52, 46, 40, 34))
    _label(img, "НОВЫЙ ПРИЁМ ИИ КАЖДЫЙ ДЕНЬ", 800, size=32)


_SCENES = {
    "hook": _scene_hook,
    "text": _scene_text,
    "prompt": _scene_prompt,
    "steps": _scene_steps,
    "number": _scene_number,
    "verdict": _scene_verdict,
    "choice": _scene_choice,
    "cta": _scene_cta,
}

# В этих сценах ведущая перекрыла бы содержание кадра — там её не рисуем.
_NO_AVATAR = {"prompt", "steps", "choice"}


def render_scene(scene, rubric, episode, out_path, with_avatar=True):
    """Рисует один кадр Shorts в PNG. Неизвестный тип сцены → обычный текст."""
    img = _bg()
    kind = scene.get("kind", "text")
    _SCENES.get(kind, _scene_text)(img, scene)
    if with_avatar and kind not in _NO_AVATAR:
        _avatar(img)
    _chrome(img, rubric, episode)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    demo = [
        {"kind": "hook", "text": "Ты платишь копирайтеру за то, что делается одной строкой"},
        {"kind": "prompt", "text": "Ты — редактор. Перепиши текст ниже так, чтобы его понял покупатель без опыта: короткие фразы, без канцелярита, в конце один вопрос клиенту. Текст: [вставь свой]"},
        {"kind": "steps", "active": 1,
         "steps": ["Открой ChatGPT", "Вставь промпт и свой текст", "Забери готовое описание"]},
        {"kind": "number", "number": "−9 часов",
         "text": "столько в неделю освобождает один промпт", "label": "Что это даёт"},
        {"kind": "verdict", "verdict": "Халяль",
         "text": "если ты не выдаёшь машинный текст за отзыв живого клиента"},
        {"kind": "choice",
         "options": ["Это честно — инструмент как инструмент",
                     "Клиент должен знать, что писал ИИ"]},
        {"kind": "cta", "text": "Сохрани и подпишись"},
    ]
    for i, s in enumerate(demo):
        print("saved", render_scene(s, "Промпт дня", 47,
                                    "output/_demo_%d_%s.png" % (i, s["kind"])))
