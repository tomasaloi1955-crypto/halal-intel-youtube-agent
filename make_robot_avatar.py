# make_robot_avatar.py — круглый аватар робота-талисмана для угла Shorts.
#
# Замена make_presenter_avatar.py: персонаж канала теперь робот (brand/robot.svg),
# тот же, что на обложках (thumbnail_html.py). Стиль кружка повторяет обложку:
# тёмно-изумрудная подложка, бирюзовое свечение, золотое кольцо.
#
# Запуск (разово, результат коммитится в репо):  python make_robot_avatar.py
import os
import re
import base64

SRC = os.path.join("brand", "robot.svg")
DST = os.path.join("brand", "robot_avatar.png")
SIZE = 440           # диаметр кружка, px
PAD = 12             # поле под тень — итоговый PNG (SIZE + 2*PAD) квадратный
# Кадр «голова + плечи» в координатах robot.svg (520x700).
VIEWBOX = "40 0 440 470"


def build_html(src=SRC, size=SIZE):
    with open(src, encoding="utf-8") as f:
        svg = f.read()
    svg = re.sub(r'viewBox="[^"]*"', f'viewBox="{VIEWBOX}"', svg, count=1)
    svg = re.sub(r'\swidth="\d+"\s+height="\d+"', "", svg, count=1)
    uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    full = size + 2 * PAD
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;background:transparent}}
.wrap{{width:{full}px;height:{full}px;position:relative}}
.av{{position:absolute;left:{PAD}px;top:{PAD - 2}px;width:{size}px;height:{size}px;border-radius:50%;
  overflow:hidden;box-sizing:border-box;border:10px solid #e0b95e;
  background:radial-gradient(60% 60% at 50% 42%, rgba(45,212,191,.45), transparent 75%),
             linear-gradient(135deg,#0c2a2e,#050b12);
  box-shadow:0 4px 14px rgba(0,0,0,.5), inset 0 0 24px rgba(233,200,128,.25)}}
.av img{{position:absolute;left:6%;top:12%;width:88%;height:94%;object-fit:contain;
  filter:drop-shadow(0 10px 16px rgba(0,0,0,.45))}}
</style></head><body><div class="wrap"><div class="av"><img src="{uri}"></div></div></body></html>"""


def build(dst=DST, executable_path=None):
    from playwright.sync_api import sync_playwright
    full = SIZE + 2 * PAD
    with sync_playwright() as p:
        kw = {"args": ["--no-sandbox"]}
        if executable_path:
            kw["executable_path"] = executable_path
        browser = p.chromium.launch(**kw)
        page = browser.new_page(viewport={"width": full, "height": full})
        page.set_content(build_html())
        page.wait_for_timeout(300)
        page.screenshot(path=dst, omit_background=True, clip={"x": 0, "y": 0, "width": full, "height": full})
        browser.close()
    print(f"[AVATAR] Готово: {dst} ({full}x{full})")
    return dst


if __name__ == "__main__":
    build(executable_path=os.environ.get("CHROMIUM_PATH") or None)
