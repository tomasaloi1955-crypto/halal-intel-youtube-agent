# make_presenter_avatar.py — делает круглый аватар ведущей из brand/presenter.png.
#
# ЗАЧЕМ. У канала есть персонаж-ведущая (ИИ-аватар), но она жила только на обложках.
# Внутри роликов канал был безликим: чужой сток + жёлтые титры, как у тысячи других.
# Постоянный маленький аватар в углу каждого Shorts даёт узнавание «это Халяль
# Интеллидженс» без съёмки живого человека (см. docs/CONTENT_STRATEGY.md).
#
# Запуск (разово, результат коммитится в репо):  python make_presenter_avatar.py
# Исходник brand/presenter.png НЕ трогаем — читаем и делаем отдельный файл.
import os

from PIL import Image, ImageDraw, ImageFilter

SRC = os.path.join("brand", "presenter.png")
DST = os.path.join("brand", "presenter_avatar.png")

# Квадрат вокруг головы и плеч в координатах presenter.png (704x768).
# Подобран так, чтобы попали лицо, хиджаб и указывающая рука, но НЕ попали
# артефакты исходника: жёлтые обрезки карточек слева и ноутбук справа снизу.
CROP_BOX = (135, 10, 595, 470)
SIZE = 440           # итоговый размер аватара, px
RING = 10            # толщина золотого кольца
GOLD = (212, 175, 55, 255)


def build(src=SRC, dst=DST, size=SIZE):
    im = Image.open(src).convert("RGBA").crop(CROP_BOX).resize((size, size), Image.LANCZOS)

    # Круглая маска со сглаженным краем (рисуем крупнее и уменьшаем — мягкое антиалиасинг-кольцо).
    ss = 4
    mask = Image.new("L", (size * ss, size * ss), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * ss - 1, size * ss - 1), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)

    # Внутри круга оставляем только непрозрачные пиксели исходника: если у ведущей
    # уже вырезан фон, в кружок не попадёт жёлтый прямоугольник от подложки.
    mask = Image.composite(mask, Image.new("L", (size, size), 0), im.getchannel("A").point(lambda a: 255 if a > 8 else 0))

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)

    # Тёмная подложка-кружок под ведущей, чтобы аватар читался на светлом b-roll.
    plate = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(plate).ellipse((RING, RING, size - RING - 1, size - RING - 1), fill=(18, 20, 32, 235))
    plate.alpha_composite(out)
    out = plate

    # Золотое кольцо по краю — фирменный цвет канала (тот же, что в титрах/обложках).
    ring = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        (RING * ss // 2, RING * ss // 2, size * ss - RING * ss // 2 - 1, size * ss - RING * ss // 2 - 1),
        outline=GOLD, width=RING * ss)
    out.alpha_composite(ring.resize((size, size), Image.LANCZOS))

    # Мягкая тень, чтобы кружок не «прилипал» к фону ролика.
    shadow = Image.new("RGBA", (size + 24, size + 24), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((12, 14, size + 11, size + 13), fill=(0, 0, 0, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(7))
    shadow.alpha_composite(out, (12, 10))

    shadow.save(dst, "PNG")
    print(f"[AVATAR] Готово: {dst} ({shadow.size[0]}x{shadow.size[1]})")
    return dst


if __name__ == "__main__":
    build()
