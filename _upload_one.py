# Разовая загрузка готового ролика на YouTube
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from youtube_uploader import upload_video

VIDEO = "output/the_white_house_is_asking_open_s_shorts.mp4"
THUMB = "output/the_white_house_is_asking_open_s_thumb.jpg"

TITLE = "Белый дом просит OpenAI притормозить новую модель 🤖"

DESCRIPTION = (
    "Белый дом обратился к OpenAI с просьбой не спешить с релизом новой модели. "
    "Разбираем, что это значит для индустрии ИИ.\n\n"
    "🕌 Халяль Интеллидженс — новости и разбор искусственного интеллекта.\n\n"
    "#OpenAI #ИИ #искусственныйинтеллект #новости #технологии #AI"
)

TAGS = [
    "OpenAI", "Белый дом", "ИИ", "искусственный интеллект",
    "новости ИИ", "технологии", "AI news", "нейросети",
]

vid_id = upload_video(VIDEO, THUMB, TITLE, DESCRIPTION, TAGS, is_shorts=True)
if vid_id:
    print(f"\nГОТОВО: https://youtube.com/shorts/{vid_id}")
else:
    print("\nЗагрузка не удалась — смотри ошибку выше.")
