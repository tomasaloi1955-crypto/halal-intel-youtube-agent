# thumbnail_html.py — фирменные обложки: HTML/CSS → PNG через headless-браузер.
# Тёмный изумрудный фон с орнаментом, золотая арка, робот-талисман (SVG),
# заголовок Unbounded, плашки Manrope. Шрифты встраиваются из brand/fonts —
# рендер не зависит от доступа к Google Fonts.
import os
import base64
import html as _html

# Персонаж справа на обложке. Раньше была ведущая (brand/presenter.png) —
# заменили на робота: канал про ИИ, робот читается сразу и без лица человека.
PRESENTER_PATH = os.path.join("brand", "robot.svg")


FONT_TITLE = os.path.join("brand", "fonts", "Unbounded-ExtraBold.ttf")
FONT_CHIP = os.path.join("brand", "fonts", "Manrope-ExtraBold.ttf")

_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".ttf": "font/ttf"}


def _data_uri(path):
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        mime = _MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return ""


def _split_subtitle(sub):
    """Разбивает подзаголовок на 1-2 плашки."""
    sub = (sub or "").strip()
    if not sub:
        return []
    words = sub.split()
    if len(words) >= 4:
        mid = (len(words) + 1) // 2
        return [" ".join(words[:mid]), " ".join(words[mid:])]
    return [sub]


TITLE_W = 610          # ширина колонки заголовка, px
TITLE_MAX_H = 360      # заголовок не должен наезжать на плашки
TITLE_MAX, TITLE_MIN = 118, 50

# Орнамент: 8-конечная звезда (рубь аль-хизб) — тонкой золотой линией, еле заметно.
_PATTERN = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'>"
    "<g fill='none' stroke='%23d9b56a' stroke-width='1.2' stroke-opacity='.55'>"
    "<rect x='35' y='35' width='50' height='50'/>"
    "<rect x='35' y='35' width='50' height='50' transform='rotate(45 60 60)'/>"
    "<circle cx='60' cy='60' r='10'/>"
    "<path d='M0 0 L20 20 M120 0 L100 20 M0 120 L20 100 M120 120 L100 100'/>"
    "</g></svg>"
)


def build_html(cover_text, cover_subtitle, presenter_path=PRESENTER_PATH):
    title = _html.escape((cover_text or "").upper())
    chips = _split_subtitle(cover_subtitle)
    boxes = "".join(
        f'<div class="chip {"chip-gold" if i == 0 else "chip-glass"}">{_html.escape(b.upper())}</div>'
        for i, b in enumerate(chips)
    )
    presenter_uri = _data_uri(presenter_path)
    presenter_html = f'<img class="presenter" src="{presenter_uri}">' if presenter_uri else ""
    f_title = _data_uri(FONT_TITLE)
    f_chip = _data_uri(FONT_CHIP)

    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
@font-face{{font-family:'CoverTitle';src:url({f_title}) format('truetype');font-weight:800}}
@font-face{{font-family:'CoverChip';src:url({f_chip}) format('truetype');font-weight:800}}
*{{margin:0;padding:0;box-sizing:border-box}}
.tb{{position:relative;width:1280px;height:720px;overflow:hidden;
  background:
    radial-gradient(520px 520px at 1000px 380px, rgba(45,212,191,.28), transparent 70%),
    radial-gradient(700px 500px at 0 0, rgba(217,181,106,.16), transparent 70%),
    linear-gradient(135deg, #0c2a2e 0%, #081a22 45%, #050b12 100%);}}
.pattern{{position:absolute;inset:0;opacity:.13;
  background-image:url("data:image/svg+xml;utf8,{_PATTERN}");background-size:120px 120px;
  -webkit-mask-image:linear-gradient(90deg, transparent 0%, #000 45%, #000 100%);}}
.frame{{position:absolute;inset:22px;border:1.5px solid rgba(217,181,106,.45);border-radius:28px;z-index:1;pointer-events:none}}
/* Арка-михраб за роботом: золотой контур + свечение. */
.arch{{position:absolute;right:92px;bottom:-40px;width:470px;height:660px;z-index:1;
  border:3px solid rgba(233,200,128,.85);border-bottom:none;border-radius:235px 235px 0 0;
  background:radial-gradient(80% 60% at 50% 45%, rgba(45,212,191,.22), rgba(8,26,34,0) 70%);
  box-shadow:0 0 40px rgba(233,200,128,.25), inset 0 0 60px rgba(233,200,128,.12);}}
.arch2{{position:absolute;right:70px;bottom:-40px;width:514px;height:704px;z-index:1;
  border:1px solid rgba(233,200,128,.35);border-bottom:none;border-radius:257px 257px 0 0}}
.left{{position:absolute;left:72px;top:40px;bottom:40px;width:{TITLE_W}px;z-index:3;
  display:flex;flex-direction:column;justify-content:center}}
.kicker{{display:flex;align-items:center;gap:14px;margin-bottom:26px;
  font-family:'CoverChip',sans-serif;font-weight:800;font-size:22px;letter-spacing:6px;color:#e9c880}}
.kicker:before{{content:"";width:56px;height:3px;border-radius:2px;background:linear-gradient(90deg,#e9c880,#b8863b)}}
.title{{font-family:'CoverTitle','Arial Black',sans-serif;font-weight:800;font-size:{TITLE_MAX}px;
  line-height:1.02;color:#fbf7ee;letter-spacing:-1px;text-transform:uppercase;
  text-shadow:0 6px 30px rgba(0,0,0,.45);}}
.title .last{{background:linear-gradient(180deg,#fff1c7 0%,#e9c880 45%,#b8863b 100%);
  -webkit-background-clip:text;background-clip:text;color:transparent;text-shadow:none;
  filter:drop-shadow(0 6px 24px rgba(233,200,128,.25))}}
.chips{{margin-top:38px;display:flex;flex-wrap:wrap;gap:16px;align-items:center;max-width:{TITLE_W}px}}
.chip{{font-family:'CoverChip',sans-serif;font-weight:800;font-size:36px;letter-spacing:1px;
  padding:14px 30px;border-radius:999px;white-space:nowrap;text-transform:uppercase}}
.chip-gold{{color:#0a1a20;background:linear-gradient(180deg,#f6dc9c,#d9a94f);
  box-shadow:0 10px 30px rgba(217,169,79,.35), inset 0 1px 0 rgba(255,255,255,.6)}}
.chip-glass{{color:#e8fbf8;background:rgba(255,255,255,.07);border:2px solid rgba(45,212,191,.7);
  box-shadow:0 0 24px rgba(45,212,191,.25)}}
.presenter{{position:absolute;right:100px;bottom:-6px;height:620px;z-index:2;
  filter:drop-shadow(0 20px 40px rgba(0,0,0,.55)) drop-shadow(0 0 30px rgba(45,212,191,.25))}}
.sparkle{{position:absolute;z-index:3;color:#e9c880;font-size:34px;text-shadow:0 0 14px rgba(233,200,128,.8)}}
</style></head>
<body><div class="tb">
  <div class="pattern"></div>
  <div class="arch2"></div><div class="arch"></div>
  {presenter_html}
  <div class="sparkle" style="right:560px;top:96px">&#10022;</div>
  <div class="sparkle" style="right:70px;top:190px;font-size:24px">&#10022;</div>
  <div class="left">
    <div class="kicker">ИИ · ПРОСТО</div>
    <div class="title" id="t">{title}</div>
    <div class="chips">{boxes}</div>
  </div>
  <div class="frame"></div>
</div>
<script>
// Последнее слово заголовка — золотом.
(function(){{
  var t=document.getElementById('t'); var w=t.textContent.trim().split(/\s+/);
  if(w.length>1){{var l=w.pop(); t.innerHTML=w.join(' ')+' <span class="last">'+l+'</span>';}}
}})();
// Кегль подбирается по факту: ни одно слово не вылезает за колонку, и заголовок
// не выше TITLE_MAX_H. Меряем после загрузки шрифта — иначе меряем запасной.
window.__fit=function(){{
  var t=document.getElementById('t'), s={TITLE_MAX};
  function over(){{
    return t.scrollWidth>{TITLE_W}+1||t.offsetHeight>{TITLE_MAX_H};
  }}
  t.style.wordBreak='keep-all';
  while(s>{TITLE_MIN}&&over()){{s-=2;t.style.fontSize=s+'px';}}
  // Плашки не переносятся — длинную уменьшаем, чтобы не заезжала на робота.
  document.querySelectorAll('.chip').forEach(function(c){{
    var cs=36; while(cs>22&&c.offsetWidth>{TITLE_W}){{cs-=2;c.style.fontSize=cs+'px';}}
  }});
  return s;
}};
</script></body></html>"""


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
                page.evaluate("document.fonts.ready.then(() => window.__fit())")
            except Exception:
                pass
            page.wait_for_timeout(300)
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
