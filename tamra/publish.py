# publish.py — публикация готового ролика Tamra School в Instagram Reels, YouTube Shorts и TikTok.
#
# У Tamra School свои аккаунты, поэтому и ключи свои (префикс TAMRA_), отдельно от канала
# «Халяль Интеллидженс». Площадка без ключей просто пропускается — остальные публикуются.
#
#   Instagram: TAMRA_IG_USER_ID, TAMRA_IG_ACCESS_TOKEN
#     (как получить — шапка instagram_poster.py, только для аккаунта Tamra School)
#   YouTube:   подключается из бота командой «ютуб» (tamra/yt_auth.py) — или секретом
#     TAMRA_YOUTUBE_TOKEN_JSON: содержимое youtube_token.json канала Tamra School
#   TikTok:    TAMRA_TIKTOK_ACCESS_TOKEN, TAMRA_TIKTOK_REFRESH_TOKEN (приложение TikTok то же,
#     что у основного канала: TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET)
import os
import json
import time
import requests

GRAPH = "https://graph.facebook.com/v19.0"


def _env(k):
    return (os.getenv(k) or "").strip()


def instagram_reel(video_path, caption, thumb_offset_ms=1000):
    """Reels через Instagram Graph API с прямой загрузкой файла (resumable upload) —
    публичная ссылка на видео не нужна. Возвращает id публикации или бросает исключение."""
    uid, token = _env("TAMRA_IG_USER_ID"), _env("TAMRA_IG_ACCESS_TOKEN")
    if not uid or not token:
        return None
    r = requests.post(f"{GRAPH}/{uid}/media", params={
        "access_token": token, "media_type": "REELS", "upload_type": "resumable",
        "caption": caption[:2200], "share_to_feed": "true", "thumb_offset": thumb_offset_ms,
    }, timeout=60)
    r.raise_for_status()
    container = r.json()
    with open(video_path, "rb") as f:
        up = requests.post(container["uri"], headers={
            "Authorization": f"OAuth {token}", "offset": "0",
            "file_size": str(os.path.getsize(video_path)),
        }, data=f, timeout=600)
    up.raise_for_status()

    cid = container["id"]
    for _ in range(60):  # Instagram обрабатывает видео до нескольких минут
        st = requests.get(f"{GRAPH}/{cid}", params={"access_token": token, "fields": "status_code,status"},
                          timeout=30).json()
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram не принял видео: {st.get('status')}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram слишком долго обрабатывает видео")
    pub = requests.post(f"{GRAPH}/{uid}/media_publish",
                        params={"access_token": token, "creation_id": cid}, timeout=60)
    pub.raise_for_status()
    return pub.json().get("id")


def youtube_short(video_path, title, description, tags, token_json=None):
    raw = token_json or _env("TAMRA_YOUTUBE_TOKEN_JSON")
    if not raw:
        return None
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials.from_authorized_user_info(json.loads(raw.strip().lstrip("\ufeff")))
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    yt = build("youtube", "v3", credentials=creds)
    if "#Shorts" not in title:
        title = title[:88] + " #Shorts"
    body = {
        "snippet": {"title": title[:100], "description": description[:5000],
                    "tags": [t.lstrip("#") for t in tags][:30],
                    "categoryId": "27",  # Education
                    "defaultLanguage": "ru"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(video_path, mimetype="video/mp4", resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


def tiktok(video_path, caption):
    from tiktok_uploader import upload_to_tiktok, _valid_access_token
    if not _valid_access_token("TAMRA_"):
        return None
    direct = _env("TAMRA_TIKTOK_DIRECT_POST").lower() in ("1", "true", "yes")
    pid = upload_to_tiktok(video_path, caption=caption, direct_post=direct, account="TAMRA_")
    if not pid:
        raise RuntimeError("TikTok не принял видео (подробности в логе)")
    return pid


def publish_all(video_path, texts, caption, yt_token=None):
    """Публикует во все настроенные площадки. Возвращает {площадка: строка-итог для Telegram}."""
    tags = texts.get("hashtags", [])
    jobs = [
        ("Instagram", lambda: instagram_reel(video_path, caption),
         lambda r: "опубликовано"),
        ("YouTube", lambda: youtube_short(video_path, texts["title"], caption, tags, yt_token),
         lambda r: f"https://youtube.com/shorts/{r}"),
        ("TikTok", lambda: tiktok(video_path, caption),
         lambda r: ("опубликовано" if _env("TAMRA_TIKTOK_DIRECT_POST").lower() in ("1", "true", "yes")
                    else "в черновиках — открой TikTok и нажми «Опубликовать»")),
    ]
    results = {}
    for name, run, ok in jobs:
        try:
            r = run()
            results[name] = ("✅ " + ok(r)) if r else "⏭ не настроено (нет ключей)"
        except Exception as e:
            detail = getattr(getattr(e, "response", None), "text", "") or ""
            print(f"[TAMRA] {name}: {e} {detail[:300]}")
            results[name] = f"🔴 ошибка: {str(e)[:150]}"
    return results
