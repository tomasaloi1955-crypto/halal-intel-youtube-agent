# thumbnail_html.py — обложки в стиле «инфлюенсер»: HTML/CSS → PNG через headless-браузер.
# Градиент + объёмный 3D-заголовок + жёлтые плашки-подзаголовки + ведущая (PNG без фона).
import os
import base64
import html as _html

PRESENTER_PATH = os.path.join("brand", "presenter.png")


def _data_uri(path):
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""


def _split_subtitle(sub):
    """Разбивает подзаголовок на 1-2 плашки (как в образце)."""
    sub = (sub or "").strip()
    if not sub:
        return []
    words = sub.split()
    if len(words) >= 4:
        mid = (len(words) + 1) // 2
        return [" ".join(words[:mid]), " ".join(words[mid:])]
    return [sub]


def build_html(cover_text, cover_subtitle, presenter_path=PRESENTER_PATH):
    title = _html.escape((cover_text or "").upper())
    boxes = "".join(
        f'<div class="chip">{_html.escape(b.upper())}</div>'
        for b in _split_subtitle(cover_subtitle)
    )
    presenter_uri = _data_uri(presenter_path)
    presenter_html = f'<img class="presenter" src="{presenter_uri}">' if presenter_uri else ""

    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@800;900&display=swap');
*{{margin:0;padding:0;box-sizing:border-box}}
.tb{{position:relative;width:1280px;height:720px;overflow:hidden;
  font-family:'Montserrat','Arial Black',sans-serif;
  background:radial-gradient(120% 120% at 72% 38%, #f6b73c 0%, #e8901a 42%, #b5650d 100%);}}
.left{{position:absolute;left:48px;top:40px;width:760px;z-index:3}}
.title{{font-weight:900;font-size:150px;line-height:.92;color:#fff;text-transform:uppercase;
  letter-spacing:-2px;
  text-shadow:
    -3px -3px 0 #2b2b2b, 3px -3px 0 #2b2b2b, -3px 3px 0 #2b2b2b, 3px 3px 0 #2b2b2b,
    4px 5px 0 #c9c9c9, 6px 8px 0 #9a9a9a, 8px 11px 0 #6f6f6f, 10px 16px 18px rgba(0,0,0,.45);}}
.chips{{margin-top:34px;display:flex;flex-direction:column;gap:20px;align-items:flex-start}}
.chip{{background:#181818;color:#ffd23b;font-weight:900;font-size:52px;
  padding:16px 30px;border-radius:16px;text-transform:uppercase;letter-spacing:.5px;
  box-shadow:4px 6px 0 rgba(0,0,0,.35);white-space:nowrap}}
.presenter{{position:absolute;right:0;bottom:0;height:730px;z-index:2;
  filter:drop-shadow(-10px 0 24px rgba(0,0,0,.25))}}
</style></head>
<body><div class="tb">
  <div class="left">
    <div class="title">{title}</div>
    <div class="chips">{boxes}</div>
  </div>
  {presenter_html}
</div></body></html>"""


def render(cover_text, cover_subtitle, output_path, presenter_path=PRESENTER_PATH):
    """Рендерит HTML-обложку в PNG 1280x720. Возвращает путь или None."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"[THUMB-HTML] Playwright недоступен: {e}")
        return None
    html_str = build_html(cover_text, cover_subtitle, presenter_path)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
            page.set_content(html_str, wait_until="networkidle")
            try:
                page.evaluate("document.fonts.ready")
            except Exception:
                pass
            page.wait_for_timeout(400)
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            page.screenshot(path=output_path, clip={"x": 0, "y": 0, "width": 1280, "height": 720})
            browser.close()
        return output_path
    except Exception as e:
        print(f"[THUMB-HTML] Ошибка рендера: {e}")
        return None


if __name__ == "__main__":
    out = render("Больше продаж 24/7", "Автоматизируй всё что можно", "output/_thumb_html_test.jpg")
    print("OUT:", out)
