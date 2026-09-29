# send_custom_posts.py — готовые посты (текст написан заранее) + фото/видео со стока →
# в Telegram владелице, чтобы переслать клиенту. Посты лежат в custom_posts.json:
#   {"channel": "подпись на обложке", "posts": [{"text": "...", "title": "...", "photo_query": "..."}]}
#   python send_custom_posts.py custom_posts.json
import json
import os
import sys

from post_media import make_post_media
from telegram_notify import notify, send_post

OUT_DIR = os.path.join("output", "custom")


def main(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    notify(f"🎯 Посты для «{data['channel']}» — {len(data['posts'])} шт. Ниже, готовые к пересылке.")
    for i, post in enumerate(data["posts"], 1):
        media = make_post_media(post["title"], post["photo_query"],
                                os.path.join(OUT_DIR, f"post_{i}"), caption=data["channel"],
                                want=tuple(post.get("want", ["photo"])))
        print(f"[custom] {i}: {post['title']} → {media}")
        send_post(post["text"], photo=media.get("photo"), video=media.get("video"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "custom_posts.json")
