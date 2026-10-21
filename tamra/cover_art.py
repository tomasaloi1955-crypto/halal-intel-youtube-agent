# cover_art.py — игровые обложки «из кубиков» для роликов Tamra School.
#
# Картинку рисует нейросеть, текст — мы сами (нейросети путают кириллицу):
#   • сцена: объёмные кубики в духе Minecraft — робот с гладким экраном вместо лица (без глаз
#     и рта), финиковая пальма и финик из кубиков, ноутбук, книги — в цветах школы, верх кадра
#     пустой под заголовок. Людей и лиц нет (картинку проверяет ИИ, как сток);
#   • сверху — белая плашка с крупным хуком и изумрудная полоска «ДЕНЬ N · TAMRA SCHOOL».
#
# Генератор: Gemini (gemini-2.5-flash-image), если ключ рабочий, иначе Pollinations (без ключа).
# Сцену под тему ролика описывает writer (texts["cover_scene"]); seed хранится в черновике,
# чтобы пересборка перед публикацией нарисовала ту же картинку.
import base64
import os
import random
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw

from tamra import brand

W, H = brand.W, brand.H
STYLE = ("3D voxel art, chunky blocky toy style like Minecraft, glossy plastic bricks, "
         "cute blocky robot whose head is a smooth blank screen with no eyes and no mouth, "
         "blocky date palm tree with golden dates, {scene}, emerald green and warm gold accents, "
         "soft light-blue gradient background with subtle dots, objects in the lower two thirds, "
         "top third is empty plain background, bright cheerful lighting, high detail, "
         "no text, no letters, no logos, no people, no human faces, no animals")

ART_PROMPT = """Это картинка для обложки детской исламской онлайн-школы. Посмотри на {n} изображени(е/я).
Нельзя: люди или их части, человеческие лица (в том числе у игрушек и роботов: глаза, рот),
животные, алкоголь, свинина, кресты, музыкальные инструменты, читаемый текст или буквы.
Ответь CLEAN, если ничего из этого нет, иначе REJECT. Одним словом."""


def _gemini(prompt):
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    r = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent",
        params={"key": key}, timeout=180,
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"responseModalities": ["IMAGE"],
                                   "imageConfig": {"aspectRatio": "9:16"}}})
    r.raise_for_status()
    for part in r.json()["candidates"][0]["content"]["parts"]:
        data = part.get("inlineData") or part.get("inline_data")
        if data:
            return base64.b64decode(data["data"])
    return None


def _pollinations(prompt, seed):
    url = (f"https://image.pollinations.ai/prompt/{quote(prompt)}"
           f"?width={W}&height={H}&seed={seed}&nologo=true&model=flux")
    r = requests.get(url, timeout=240)
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError("Pollinations вернул не картинку")
    return r.content


def generate(scene, seed, out_path):
    """Рисует фон обложки в out_path. True — получилось и прошло проверку."""
    from people_filter import vision_check
    prompt = STYLE.format(scene=scene or "laptop, open books and pencils on a blocky desk")
    for attempt in range(3):
        data = None
        try:
            data = _gemini(prompt) if attempt == 0 else None
        except Exception as e:
            print(f"[TAMRA] Gemini-картинка недоступна: {e}")
        try:
            data = data or _pollinations(prompt, seed + attempt)
        except Exception as e:
            print(f"[TAMRA] Pollinations недоступен: {e}")
            continue
        with open(out_path, "wb") as f:
            f.write(data)
        try:
            Image.open(out_path).convert("RGB").save(out_path, "JPEG", quality=92)
        except Exception:
            continue
        if vision_check([out_path], ART_PROMPT, "CLEAN"):
            return True
    if os.path.exists(out_path):
        os.remove(out_path)
    return False


def new_seed():
    return random.randint(1, 10_000_000)


def compose(art_path, hook, day, out_png):
    """Готовая обложка 1080×1920: фон-картинка + плашка с хуком + полоска дня + логотип."""
    from tamra.montage import _font, _fit
    bg = Image.open(art_path).convert("RGB")
    s = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * s) + 1, int(bg.height * s) + 1), Image.LANCZOS)
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    img = bg.crop((left, top, left + W, top + H)).convert("RGBA")
    d = ImageDraw.Draw(img)

    # белая плашка с толстой чёрной рамкой и крупным заголовком
    x0, x1, y0 = 60, W - 60, 150
    f, lines, size = _fit(d, (hook or "").upper(), x1 - x0 - 90, 470, [124, 110, 96, 84, 72, 62])
    lh = int(size * 1.08)
    box_h = len(lines) * lh + 90
    d.rounded_rectangle((x0, y0, x1, y0 + box_h), radius=44, fill=(255, 255, 255, 255),
                        outline=(18, 18, 18, 255), width=8)
    y = y0 + 45
    for ln in lines:
        d.text(((W - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=(18, 18, 18))
        y += lh

    # изумрудная полоска «ДЕНЬ N · TAMRA SCHOOL», наезжает на низ плашки, как в образце
    pf = _font(54)
    pill = f"ДЕНЬ {day} · {brand.BRAND_NAME}"
    pw = d.textlength(pill, font=pf) + 90
    py = y0 + box_h - 36
    d.rounded_rectangle(((W - pw) / 2, py, (W + pw) / 2, py + 92), radius=46,
                        fill=brand.EMERALD + (255,), outline=(255, 255, 255, 255), width=5)
    d.text(((W - pw) / 2 + 45, py + 14), pill, font=pf, fill=brand.CREAM)

    # логотип-финик в углу
    from tamra.montage import LOGO
    if os.path.exists(LOGO):
        logo = Image.open(LOGO).convert("RGBA").resize((150, 150), Image.LANCZOS)
        img.alpha_composite(logo, (W - 150 - 50, H - 150 - 330))
    img.save(out_png)
    return out_png
