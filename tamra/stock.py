# stock.py — стоковые кадры для ролика, когда клипов нет и пришла только озвучка.
#
# Школа для детей, поэтому в кадре — дети: детские руки над тетрадью и ноутбуком, силуэты,
# дети в классе со спины. Видео берутся с Pexels (PEXELS_API_KEY), сначала вертикальные.
# Лица в каждом клипе размываются (tamra/faces.py), а потом клип смотрит ИИ
# (people_filter.vision_check): различимое лицо, взрослые, открытая одежда — клип не берём.
# В сомнительном случае клип не берём. Уже использованные клипы не повторяются.
import os
import random
import requests

from people_filter import vision_check, video_frames
from tamra import faces

QUERIES = [
    "child hands writing notebook", "kid using laptop", "child hands keyboard",
    "children classroom", "child silhouette window", "kids hands tablet",
    "child reading book", "school desk pencil notebook", "kid drawing at desk",
    "children back view school",
]

KIDS_PROMPT = """Это кадр для канала исламской онлайн-школы для детей. Лица людей в кадре должны
быть размыты. Посмотри на {n} изображени(е/я) внимательно, включая фон, края, отражения.

Можно: дети и детские руки; дети со спины, в профиль без различимого лица, силуэтом; дети
в классе, если их лица РАЗМЫТЫ; тетради, книги, ноутбук, планшет, парта, карандаши.
Нельзя:
- различимое (НЕ размытое) лицо любого человека, даже частично или в отражении;
- взрослые мужчины и женщины, в том числе только их руки;
- открытая одежда (майки, шорты, открытые плечи), обтягивающая одежда;
- алкоголь, свинина, кресты, музыкальные инструменты, казино;
- чужие логотипы крупным планом и текст на экране, который можно прочитать.
Ответь CLEAN, только если ничего из запрещённого нет ни на одном изображении.
Во всех остальных случаях и если сомневаешься — REJECT. Ответь одним словом: CLEAN или REJECT."""


def _pick_file(video):
    """Файл, близкий к 1080 по короткой стороне: и чётко, и не гигабайт."""
    files = [f for f in video.get("video_files", [])
             if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
    if not files:
        return None
    short = lambda f: min(f["width"], f["height"])  # noqa: E731
    good = [f for f in files if short(f) >= 1080]
    return min(good, key=short) if good else max(files, key=short)


def search(query, orientation):
    key = os.getenv("PEXELS_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": key},
                         params={"query": query, "orientation": orientation, "per_page": 15},
                         timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"[TAMRA] Pexels «{query}»: {e}")
        return []
    out = []
    for v in r.json().get("videos", []):
        f = _pick_file(v)
        if f and 4 <= v.get("duration", 0) <= 60:
            out.append({"id": v["id"], "url": f["link"]})
    return out


def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return dest


def is_allowed(path):
    frames = video_frames(path, count=4)
    try:
        return len(frames) >= 2 and vision_check(frames, KIDS_PROMPT, "CLEAN")
    finally:
        for f in frames:
            if os.path.exists(f):
                os.remove(f)


def pick(count, used_ids, workdir, max_checks=14, queries=None):
    """Подбирает count проверенных клипов. Возвращает [{"id","url","path"}] (может быть меньше).
    queries — запросы под содержание ролика (их пишет нейросеть по озвучке, например
    «countdown timer», «child hands laptop»): идут первыми и по порядку рассказа,
    общие запросы про ноутбук и стол — только добивают недостающее."""
    if not os.getenv("PEXELS_API_KEY"):
        raise RuntimeError("нет PEXELS_API_KEY — не могу подобрать стоковые кадры")
    seen = set(used_ids)

    def fresh(q, orientation):
        out = []
        for c in search(q, orientation):
            if c["id"] not in seen:
                seen.add(c["id"])
                out.append(c)
        return out

    # по теме ролика: по паре кандидатов с каждого запроса по кругу, чтобы кадры чередовались
    themed = [fresh(q, "portrait") or fresh(q, "landscape") for q in (queries or [])]
    candidates = []
    for i in range(3):
        candidates += [lst[i] for lst in themed if len(lst) > i]

    general = []
    for orientation in ("portrait", "landscape"):
        for q in random.sample(QUERIES, len(QUERIES)):
            general += fresh(q, orientation)
        if len(general) >= count * 3:
            break
    random.shuffle(general)
    candidates += general
    max_checks += len(queries or [])  # тематические клипы чаще отсеиваются — даём им попытки

    chosen, checks = [], 0
    for c in candidates:
        if len(chosen) >= count or checks >= max_checks:
            break
        checks += 1
        raw = os.path.join(workdir, f"raw_{c['id']}.mp4")
        path = os.path.join(workdir, f"stock_{c['id']}.mp4")
        try:
            download(c["url"], raw)
            faces.blur_video(raw, path)  # лица размываем ДО проверки — ИИ смотрит готовый кадр
        except Exception as e:
            print(f"[TAMRA] Клип {c['id']} не подготовлен: {e}")
            continue
        finally:
            if os.path.exists(raw):
                os.remove(raw)
        if is_allowed(path):
            chosen.append({**c, "path": path})
        else:
            os.remove(path)
    print(f"[TAMRA] Стоковых клипов: {len(chosen)} из {count} (проверено {checks})")
    return chosen
