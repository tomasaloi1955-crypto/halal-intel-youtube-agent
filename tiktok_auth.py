# tiktok_auth.py — разовая авторизация TikTok (получение access/refresh токенов).
# Открывает браузер на страницу согласия TikTok. После разрешения TikTok
# перенаправит на https://localhost/?code=... (страница не откроется —
# это нормально, код берём из адресной строки, как делали с YouTube).
import os
import sys
import secrets
import urllib.parse
import webbrowser
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
REDIRECT_URI = "https://github.com/tomasaloi1955-crypto/halal-intel-youtube-agent"
SCOPES = "user.info.basic,video.upload"

if not CLIENT_KEY:
    print("Нет TIKTOK_CLIENT_KEY в .env")
    sys.exit(1)

state = secrets.token_urlsafe(12)
params = {
    "client_key": CLIENT_KEY,
    "scope": SCOPES,
    "response_type": "code",
    "redirect_uri": REDIRECT_URI,
    "state": state,
}
url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(params)

print(">>> Открываю браузер для авторизации TikTok...")
print(">>> Если не открылось — скопируй ссылку ниже в браузер вручную:\n")
print(url)
print("\n>>> После 'Authorize' TikTok перекинет на https://localhost/?code=... "
      "(страница не загрузится — это ОК). Скопируй ВЕСЬ адрес из строки браузера.")
try:
    webbrowser.open(url)
except Exception:
    pass
