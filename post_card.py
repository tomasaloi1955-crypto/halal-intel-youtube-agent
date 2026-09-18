# post_card.py — фирменная карточка к посту (1080×1080), рисуется Pillow.
#
# ЗАЧЕМ. AI-генератор картинок отключён 18.09.2026: он не давал гарантии, что в кадре
# не окажется человек (подробности — в шапке threads_poster.py). Но Instagram Feed без
# изображения пост не принимает, да и в ленте Threads/Telegram текст с картинкой
# заметнее. Поэтому картинку рисуем сами: здесь нет нейросети, а значит нет и
# случайностей — на карточке ровно то, что мы нарисовали.
#
# Стиль тот же, что у кадров Shorts и обложек (shorts_frames.py): тёмно-синяя база,
# фирменное золото, Montserrat, уголки-скобки. Вместо стокового фото — исламский
# геометрический узор (восьмиконечные звёзды-гирих), он же работает как фактура.
#
# Использование:
#   from post_card import make_post_card
#   path = make_post_card("Текст поста", out_path="output/card.png")
import os
import re
import time
import math
import shutil
import hashlib
import subprocess
from datetime import datetime

from PIL import Image, ImageDraw

from shorts_frames import (
    font, BG_TOP, BG_BOTTOM, GOLD, GOLD_DIM, WHITE, MUTED, TG_CHANNEL,
)

S = 1080  # карточка квадратная: одинаково хорошо ложится в Instagram, Threads и Telegram


# ── фон: градиент + исламский геометрический узор ───────────────────────────

def _star_points(cx, cy, r_out, r_in, points=8, rot=0.0):
    """Вершины звезды-гирих: лучи через один длинные и короткие."""
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = rot + i * math.pi / points
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _make_bg():
    """Фон карточки. Узор приглушён (низкая непрозрачность золота): он должен
    читаться как фактура, а не спорить с текстом поста."""
    img = Image.new("RGB", (S, S), BG_BOTTOM)
    d = ImageDraw.Draw(img)
    for y in range(S):
        t = y / S
        d.line([(0, y), (S, y)], fill=(
            int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
            int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
            int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)))

    ov = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)

    # решётка звёзд: шаг подобран так, чтобы соседние звёзды почти касались лучами
    step = 180
    for gx in range(-1, S // step + 2):
        for gy in range(-1, S // step + 2):
            cx, cy = gx * step + step // 2, gy * step + step // 2
            od.polygon(_star_points(cx, cy, 62, 26, 8, math.pi / 8),
                       outline=(*GOLD, 34))
            od.polygon(_star_points(cx, cy, 30, 13, 8, math.pi / 8),
                       outline=(*GOLD, 22))
            # ромбы между звёздами — то, что и превращает россыпь звёзд в узор
            od.polygon([(cx + step // 2, cy), (cx + step, cy - step // 2),
                        (cx + step + step // 2, cy), (cx + step, cy + step // 2)],
                       outline=(*GOLD, 16))

    # золотое свечение по центру — даёт глубину и притягивает взгляд к тексту
    cx = cy = S // 2
    for r in range(520, 0, -8):
        od.ellipse((cx - r, cy - r, cx + r, cy + r),
                   fill=(*GOLD, int(13 * (1 - r / 520) ** 0.6)))

    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

    # уголки-скобки — та же рамка, что на кадрах Shorts: узнаваемость канала
    d = ImageDraw.Draw(img)
    m, sz = 52, 150
    for (x0, y0, x1, y1, x2, y2) in [
        (m, m + sz, m, m, m + sz, m),
        (S - m - sz, m, S - m, m, S - m, m + sz),
        (m, S - m - sz, m, S - m, m + sz, S - m),
        (S - m - sz, S - m, S - m, S - m, S - m, S - m - sz),
    ]:
        d.line([(x0, y0), (x1, y1), (x2, y2)], fill=GOLD_DIM, width=3)
    return img


_BG_CACHE = []


def _bg():
    if not _BG_CACHE:
        _BG_CACHE.append(_make_bg())
    return _BG_CACHE[0].copy()


# ── текст ────────────────────────────────────────────────────────────────────

def _wrap(d, text, f, max_w):
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


def hook(text, limit=140):
    """Главная мысль поста для карточки.

    Целиком пост (до 498 знаков) на картинку класть нельзя: кегль упадёт до
    нечитаемого, а смысл карточки — чтобы фраза цепляла на лету. Берём первое
    предложение, и только если оно короткое — добавляем следующее.
    Знаки препинания сохраняем: без них два предложения слипаются в кашу
    («не заберут твою работу Её заберёт тот...»)."""
    text = " ".join((text or "").split())
    if not text:
        return ""
    # ссылки на карточке не нужны — их всё равно не скопируешь с картинки
    text = " ".join(w for w in text.split()
                    if not w.startswith(("http://", "https://", "t.me/", "@")))

    sentences = [s.strip() for s in re.findall(r"[^.!?…]+[.!?…]*", text) if s.strip()]
    if not sentences:
        return text[:limit].rsplit(" ", 1)[0] + "…"

    out = sentences[0]
    for nxt in sentences[1:]:
        if len(out) + 1 + len(nxt) > limit:
            break
        out = out + " " + nxt

    if len(out) > limit + 40:  # одно очень длинное предложение — обрезаем по слову
        out = out[:limit + 40].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    return out


def _draw_text(img, text):
    """Текст по центру карточки с автоподбором кегля: длина фразы у нейросети
    каждый раз разная, фиксированный кегль либо обрежет её, либо оставит пустоту."""
    d = ImageDraw.Draw(img)
    max_w, max_h = S - 260, 520
    for size in (86, 78, 70, 62, 56, 50, 44, 40):
        f = font(size, bold=True)
        lines = _wrap(d, text, f, max_w)
        lh = int(size * 1.26)
        if len(lines) * lh <= max_h:
            break
    y = (S - len(lines) * lh) // 2
    for ln in lines:
        lw = d.textlength(ln, font=f)
        x = (S - lw) / 2
        d.text((x + 3, y + 4), ln, font=f, fill=(0, 0, 0))  # тень для читаемости
        d.text((x, y), ln, font=f, fill=WHITE)
        y += lh
    return y


def make_post_card(post_text, out_path="output/post_card.png", rubric="ИИ И АВТОМАТИЗАЦИЯ"):
    """Рисует карточку к посту и возвращает путь к файлу."""
    img = _bg()
    d = ImageDraw.Draw(img)

    # рубрика сверху
    f_rub = font(30, bold=True)
    rw = d.textlength(rubric, font=f_rub)
    d.text(((S - rw) / 2, 118), rubric, font=f_rub, fill=GOLD)
    d.line([((S - rw) / 2 - 30, 168), ((S + rw) / 2 + 30, 168)], fill=GOLD_DIM, width=2)

    bottom = _draw_text(img, hook(post_text))

    # подпись канала снизу
    f_tg = font(32, bold=True)
    tw = d.textlength(TG_CHANNEL, font=f_tg)
    d.text(((S - tw) / 2, max(bottom + 60, S - 150)), TG_CHANNEL, font=f_tg, fill=MUTED)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    # JPEG, а не PNG: Instagram Graph API принимает только JPEG и молча отклоняет
    # остальное. Качество 92 — на сплошной заливке с текстом артефактов не видно.
    if out_path.lower().endswith((".jpg", ".jpeg")):
        img.save(out_path, "JPEG", quality=92, optimize=True)
    else:
        img.save(out_path)
    return out_path


def publish_to_repo(local_path, subdir="cards", keep_days=30):
    """Кладёт карточку в сам репозиторий и возвращает прямую ссылку на неё.

    ЗАЧЕМ ТАК. Threads и Instagram принимают картинку ТОЛЬКО по публичному URL —
    залить файл байтами их API не позволяет. Заводить ради одной картинки в день
    внешний хостинг не хочется (ещё один ключ, ещё одна точка отказа), а
    репозиторий и так публичный, и бот уже коммитит в него состояние каждый день.
    Поэтому хостингом работает он сам: файл коммитится и отдаётся через
    raw.githubusercontent.com.

    Имя файла — с датой и хешем текста, а не постоянное: raw.githubusercontent
    кэширует ответ на несколько минут, и при перезаписи одного и того же имени
    соцсеть могла бы забрать вчерашнюю карточку.

    Возвращает None, если запуск не в GitHub Actions или push не удался — тогда
    пост просто уйдёт без картинки, это не повод ронять публикацию.
    """
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print("[CARD] Не GitHub Actions — карточку публиковать некуда, пост уйдёт текстом.")
        return None
    branch = os.environ.get("GITHUB_REF_NAME") or "master"

    os.makedirs(subdir, exist_ok=True)
    dst = os.path.join(subdir, os.path.basename(local_path))
    if os.path.abspath(dst) != os.path.abspath(local_path):
        shutil.copyfile(local_path, dst)

    def _git(*args, check=True):
        return subprocess.run(["git", *args], check=check,
                              capture_output=True, text=True)

    try:
        _git("config", "user.name", "autopilot")
        _git("config", "user.email", "autopilot@users.noreply.github.com")

        # чистим старые карточки, чтобы репозиторий не разрастался
        cutoff = time.time() - keep_days * 86400
        for name in os.listdir(subdir):
            p = os.path.join(subdir, name)
            if p != dst and os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                _git("rm", "-f", "--ignore-unmatch", p, check=False)

        _git("add", dst)
        # если карточка ровно та же (повторный запуск в тот же день) — коммитить нечего,
        # но файл уже в репозитории, и ссылка на него рабочая
        if _git("diff", "--cached", "--quiet", check=False).returncode != 0:
            _git("commit", "-m", f"card: {os.path.basename(dst)} [skip ci]")
            if _git("push", check=False).returncode != 0:
                _git("pull", "--rebase", check=False)
                if _git("push", check=False).returncode != 0:
                    print("[CARD] Не удалось запушить карточку — пост уйдёт текстом.")
                    return None
    except Exception as e:
        print(f"[CARD] Ошибка публикации карточки: {e} — пост уйдёт текстом.")
        return None

    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{dst.replace(os.sep, '/')}"
    print(f"[CARD] Карточка опубликована: {url}")
    return url


def card_url_for_post(post_text, rubric="ИИ И АВТОМАТИЗАЦИЯ"):
    """Рисует карточку к посту и возвращает публичный URL (или None).

    Единая точка для автопостинга: любая ошибка здесь гасится — картинка приятна,
    но пост важнее, и падать из-за неё нельзя."""
    try:
        stamp = datetime.now().strftime("%Y-%m-%d")
        digest = hashlib.sha1((post_text or "").encode("utf-8")).hexdigest()[:6]
        path = make_post_card(post_text, out_path=f"output/card_{stamp}_{digest}.jpg",
                              rubric=rubric)
        return publish_to_repo(path)
    except Exception as e:
        print(f"[CARD] Не удалось нарисовать карточку: {e}")
        return None


if __name__ == "__main__":
    make_post_card(
        "7% компаний выживут после массовой автоматизации. Остальные просто исчезнут.",
        out_path="output/post_card_demo.png",
    )
    print("Готово: output/post_card_demo.png")
