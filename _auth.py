import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from youtube_uploader import get_youtube_service

print(">>> Открываю браузер для авторизации Google...")
svc = get_youtube_service()
# Проверим, что токен реально работает — запросим свой канал
me = svc.channels().list(part="snippet", mine=True).execute()
items = me.get("items", [])
if items:
    name = items[0]["snippet"]["title"]
    print(f">>> УСПЕХ! Авторизован канал: {name}")
else:
    print(">>> Токен сохранён, но канал не найден на этом аккаунте.")
print(">>> Файл youtube_token.json сохранён. Авторизация больше не понадобится.")
