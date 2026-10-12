# tiktok_uploader.py — публикация вертикальных Shorts в TikTok через Content Posting API.
#
# БЕЗОПАСНОСТЬ: ключи/токены НЕ хранятся в коде. Берутся из окружения (GitHub Secrets):
#   TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET  — из кабинета developers.tiktok.com
#   TIKTOK_ACCESS_TOKEN, TIKTOK_REFRESH_TOKEN — получаются один раз при авторизации (tiktok_auth.py)
#
# Поток: refresh access_token → init загрузки → PUT байтов видео → (черновик в inbox либо прямой пост).
# До аудита приложения TikTok работает только «inbox» (видео уходит в черновики, ты жмёшь «Опубликовать»).
import os
import json
import time
import requests
from dotenv import load_dotenv
from paths import dpath

load_dotenv()

CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")

API = "https://open.tiktokapis.com"

# account — префикс второго аккаунта (например "TAMRA_"): токены берутся из
# TAMRA_TIKTOK_ACCESS_TOKEN / TAMRA_TIKTOK_REFRESH_TOKEN и лежат в своём файле.
# Приложение TikTok (client key/secret) у аккаунтов общее, но его можно и переопределить.
# Пустой префикс — основной канал, поведение как раньше.


def _token_file(account=""):
    return dpath(f"{account.lower()}tiktok_token.json")


def _client(account=""):
    key = os.getenv(f"{account}TIKTOK_CLIENT_KEY") or CLIENT_KEY
    secret = os.getenv(f"{account}TIKTOK_CLIENT_SECRET") or CLIENT_SECRET
    return key, secret


def _seed_tokens_from_env(account=""):
    """На чистом раннере разворачиваем токены из секретов в файл (как для YouTube)."""
    if os.path.exists(_token_file(account)):
        return
    at = os.getenv(f"{account}TIKTOK_ACCESS_TOKEN")
    rt = os.getenv(f"{account}TIKTOK_REFRESH_TOKEN")
    if at and rt:
        _save_tokens({"access_token": at, "refresh_token": rt, "expires_at": 0}, account)


def _load_tokens(account=""):
    path = _token_file(account)
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_tokens(tok, account=""):
    path = _token_file(account)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tok, f, ensure_ascii=False, indent=2)


def _refresh(tok, account=""):
    """Обновляет access_token по refresh_token. TikTok access живёт ~24ч."""
    client_key, client_secret = _client(account)
    r = requests.post(
        f"{API}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
        },
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()
    if "access_token" not in d:
        raise RuntimeError(f"TikTok refresh не вернул токен: {d}")
    tok = {
        "access_token": d["access_token"],
        "refresh_token": d.get("refresh_token", tok["refresh_token"]),
        "expires_at": int(time.time()) + int(d.get("expires_in", 86400)) - 120,
    }
    _save_tokens(tok, account)
    return tok


def _valid_access_token(account=""):
    """Возвращает свежий access_token (обновляет при необходимости) или None, если TikTok не настроен."""
    client_key, client_secret = _client(account)
    if not client_key or not client_secret:
        return None
    _seed_tokens_from_env(account)
    tok = _load_tokens(account)
    if not tok or not tok.get("refresh_token"):
        return None
    if int(time.time()) >= int(tok.get("expires_at", 0)):
        tok = _refresh(tok, account)
    return tok["access_token"]


def _upload_bytes(upload_url, video_path, size):
    with open(video_path, "rb") as f:
        data = f.read()
    headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}",
    }
    r = requests.put(upload_url, headers=headers, data=data, timeout=300)
    return r.status_code in (200, 201, 206)


def upload_to_tiktok(video_path, caption="", direct_post=False, account=""):
    """
    Публикует вертикальный mp4 в TikTok.
    direct_post=False → видео уходит в черновики/inbox (работает до аудита приложения).
    direct_post=True  → прямой публичный пост (нужен пройденный аудит + scope video.publish).
    account="TAMRA_" → публикует во второй аккаунт (см. _token_file/_client).
    Возвращает publish_id или None. Никогда не роняет автопилот (все ошибки логируются).
    """
    try:
        token = _valid_access_token(account)
        if not token:
            print("[TIKTOK] Пропуск — не настроены ключи/токены TikTok.")
            return None
        if not os.path.exists(video_path):
            print(f"[TIKTOK] Нет файла: {video_path}")
            return None

        size = os.path.getsize(video_path)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        source_info = {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": size,
            "total_chunk_count": 1,
        }

        if direct_post:
            endpoint = f"{API}/v2/post/publish/video/init/"
            body = {
                "post_info": {
                    "title": caption[:2200],
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                    "disable_comment": False,
                },
                "source_info": source_info,
            }
        else:
            endpoint = f"{API}/v2/post/publish/inbox/video/init/"
            body = {"source_info": source_info}

        r = requests.post(endpoint, headers=headers, json=body, timeout=60)
        d = r.json()
        data = d.get("data", {})
        upload_url = data.get("upload_url")
        publish_id = data.get("publish_id")
        if not upload_url:
            print(f"[TIKTOK] init не дал upload_url: {d}")
            return None

        if not _upload_bytes(upload_url, video_path, size):
            print("[TIKTOK] Загрузка байтов не удалась.")
            return None

        where = "опубликовано" if direct_post else "отправлено в черновики (заверши в приложении)"
        print(f"[TIKTOK] Видео {where}. publish_id={publish_id}")
        return publish_id
    except Exception as e:
        print(f"[TIKTOK] Ошибка публикации: {e}")
        return None
