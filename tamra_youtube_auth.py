# tamra_youtube_auth.py — разовая авторизация YouTube-канала Tamra School.
#
# Запуск: двойной клик по tamra_youtube_auth.cmd (лежит рядом, в папке проекта, где есть
# youtube_credentials.json). Откроется браузер Google:
#   1) выбери свой Google-аккаунт,
#   2) на экране выбора канала выбери TAMRA SCHOOL (не Халяль Интеллидженс!),
#   3) разреши доступ.
# Скрипт покажет имя канала, сохранит tamra_youtube_token.json и скопирует его содержимое
# в буфер обмена — останется вставить в секрет GitHub TAMRA_YOUTUBE_TOKEN_JSON.
import os
import subprocess
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
CREDENTIALS_FILE = os.getenv("YOUTUBE_CREDENTIALS_FILE", "youtube_credentials.json")
TOKEN_FILE = "tamra_youtube_token.json"  # *_token.json в .gitignore — в репозиторий не попадёт

if not os.path.exists(CREDENTIALS_FILE):
    sys.exit(f"Нет файла {CREDENTIALS_FILE} в этой папке — запусти из папки проекта, "
             "где лежит youtube_credentials.json основного агента.")

print(">>> Открываю браузер. Выбери аккаунт, затем канал TAMRA SCHOOL.")
flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
creds = flow.run_local_server(port=0, prompt="select_account consent")

me = build("youtube", "v3", credentials=creds).channels().list(part="snippet", mine=True).execute()
items = me.get("items", [])
name = items[0]["snippet"]["title"] if items else "(канал не найден)"
print(f"\n>>> Авторизован канал: {name}")
if "tamra" not in name.lower():
    print(">>> ВНИМАНИЕ: это не похоже на канал Tamra School. Запусти ещё раз и выбери нужный канал.")

token_json = creds.to_json()
with open(TOKEN_FILE, "w", encoding="utf-8") as f:
    f.write(token_json)
print(f">>> Токен сохранён в {TOKEN_FILE}")

try:
    subprocess.run("clip", input=token_json.encode("utf-8"), check=True, shell=True)
    print(">>> Токен СКОПИРОВАН в буфер обмена.")
    print(">>> Открой https://github.com/tomasaloi1955-crypto/halal-intel-youtube-agent/settings/secrets/actions/new")
    print(">>> Name: TAMRA_YOUTUBE_TOKEN_JSON, Secret: Ctrl+V, затем Add secret.")
except Exception:
    print(f">>> Не удалось скопировать автоматически — открой {TOKEN_FILE} в Блокноте и скопируй всё содержимое.")
