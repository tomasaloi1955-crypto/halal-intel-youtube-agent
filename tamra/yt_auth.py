# yt_auth.py — подключение YouTube-канала Tamra School прямо с телефона, через бота.
#
# Компьютер не нужен:
#   1. В боте пишешь «ютуб» — бот присылает ссылку на вход Google.
#   2. Открываешь её на телефоне, выбираешь канал TAMRA SCHOOL, нажимаешь «Разрешить».
#   3. Google перекидывает на адрес http://localhost:8765/?...code=... — страница не
#      откроется, это нормально. Копируешь этот адрес из адресной строки и присылаешь боту.
#   4. Бот обменивает код на ключ канала и сам его хранит.
#
# OAuth-клиент — тот же, что у основного агента (секрет YOUTUBE_CREDENTIALS_JSON, тип
# «Desktop»: для него Google разрешает перенаправление на localhost с любым портом).
#
# Ключ канала лежит в state/tamra_state.json ЗАШИФРОВАННЫМ (Fernet): репозиторий публичный,
# а расшифровать можно только ключом, выведенным из токена бота (TAMRA_TG_TOKEN — секрет).
# Если ключа из бота нет — берётся секрет TAMRA_YOUTUBE_TOKEN_JSON.
import base64
import hashlib
import json
import os
from urllib.parse import parse_qs, urlparse

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
REDIRECT = "http://localhost:8765/"


def _client_config():
    raw = os.getenv("YOUTUBE_CREDENTIALS_JSON", "")
    if not raw:
        raise RuntimeError("нет секрета YOUTUBE_CREDENTIALS_JSON (OAuth-клиент Google)")
    return json.loads(raw)


def _flow():
    from google_auth_oauthlib.flow import Flow
    # без PKCE: ссылка выдаётся в одном запуске Actions, а код обменивается в другом —
    # хранить code_verifier пришлось бы в публичном состоянии
    return Flow.from_client_config(_client_config(), SCOPES, redirect_uri=REDIRECT,
                                   autogenerate_code_verifier=False)


def auth_url():
    url, _ = _flow().authorization_url(access_type="offline", prompt="select_account consent",
                                       include_granted_scopes="true")
    return url


def extract_code(text):
    """Код из присланного адреса localhost (или сам код, если прислали только его)."""
    text = (text or "").strip()
    if "code=" in text:
        start = text.find("http")
        qs = parse_qs(urlparse(text[start:] if start >= 0 else "http://x/?" + text).query)
        return (qs.get("code") or [None])[0]
    return None


def exchange(code):
    """Код → (token_json, имя канала)."""
    from googleapiclient.discovery import build
    flow = _flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    me = build("youtube", "v3", credentials=creds).channels().list(part="snippet", mine=True).execute()
    items = me.get("items", [])
    return creds.to_json(), (items[0]["snippet"]["title"] if items else "")


def _fernet():
    from cryptography.fernet import Fernet
    secret = os.getenv("TAMRA_TG_TOKEN", "")
    if not secret:
        raise RuntimeError("нет TAMRA_TG_TOKEN — нечем зашифровать ключ")
    key = base64.urlsafe_b64encode(hashlib.sha256(("tamra-youtube:" + secret).encode()).digest())
    return Fernet(key)


def encrypt(token_json):
    return _fernet().encrypt(token_json.encode()).decode()


def decrypt(blob):
    return _fernet().decrypt(blob.encode()).decode()


def token_json(st):
    """Ключ канала для публикации. Сначала — подключённый из бота (канал виден по имени при
    подключении), потом секрет TAMRA_YOUTUBE_TOKEN_JSON."""
    blob = st.get("yt_token_enc")
    if blob:
        try:
            return decrypt(blob)
        except Exception as e:
            print(f"[TAMRA] Не расшифровала ключ YouTube: {e}")
    # Секрет, вставленный из Windows, часто начинается с невидимого BOM — срезаем.
    env = os.getenv("TAMRA_YOUTUBE_TOKEN_JSON", "").strip().lstrip("\ufeff").strip()
    if env:
        try:
            json.loads(env)
            return env
        except ValueError:
            print("[TAMRA] Секрет TAMRA_YOUTUBE_TOKEN_JSON не читается как JSON")
    return None
