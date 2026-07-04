import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from dotenv import load_dotenv

load_dotenv()

from paths import dpath
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = dpath("youtube_token.json")
CREDENTIALS_FILE = os.getenv("YOUTUBE_CREDENTIALS_FILE", "youtube_credentials.json")


def _seed_from_env():
    """На Render (без браузера) токен/credentials передаём через env — пишем в файлы при старте."""
    token_json = os.getenv("YOUTUBE_TOKEN_JSON")
    if token_json and not os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token_json)
    cred_json = os.getenv("YOUTUBE_CREDENTIALS_JSON")
    if cred_json and not os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            f.write(cred_json)


def get_youtube_service():
    """Authenticate and return YouTube API service."""
    creds = None
    _seed_from_env()

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except Exception as e:
                # Токен отозван/протух (invalid_grant) — падаем в браузерную авторизацию.
                print(f"[YOUTUBE] refresh не удался ({e}) — нужна повторная авторизация.")
                creds = None
        if not refreshed:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Missing {CREDENTIALS_FILE}. "
                    "Download it from Google Cloud Console → APIs → YouTube Data API v3 → Credentials"
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def upload_video(video_path, thumbnail_path, title, description, tags, is_shorts=False):
    """Upload video to YouTube with thumbnail."""
    try:
        youtube = get_youtube_service()

        # Shorts need #Shorts in title/description
        if is_shorts:
            if "#Shorts" not in title:
                title = title[:90] + " #Shorts"
            if "#Shorts" not in description:
                description = "#Shorts\n\n" + description

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:30],
                "categoryId": "28",  # Science & Technology
                "defaultLanguage": "ru",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
                "madeForKids": False,
            },
        }

        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=1024 * 1024 * 5,  # 5MB chunks
        )

        print(f"[YOUTUBE] Uploading: {title}")
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"[YOUTUBE] Upload progress: {pct}%")

        video_id = response["id"]
        print(f"[YOUTUBE] Uploaded! ID: {video_id}")
        print(f"[YOUTUBE] URL: https://youtube.com/watch?v={video_id}")

        # Set thumbnail
        if thumbnail_path and os.path.exists(thumbnail_path):
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            print(f"[YOUTUBE] Thumbnail set.")

        return video_id

    except Exception as e:
        print(f"[YOUTUBE] Upload error: {e}")
        return None


if __name__ == "__main__":
    print("YouTube uploader ready. Run via main.py")
    print("First run will open browser for Google OAuth authentication.")
