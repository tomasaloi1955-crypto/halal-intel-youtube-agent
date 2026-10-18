# faces.py — размытие лиц в стоковых клипах (дети в классе, у доски, за ноутбуком).
#
# Детектор лиц — YuNet (OpenCV, модель в tamra/assets, лицензия MIT, opencv_zoo).
# Каждый кадр: ищем лица, рамку расширяем в полтора раза и сильно пикселизуем + размываем.
# Рамки держим ещё несколько кадров после последнего обнаружения, чтобы лицо не
# «мигало» открытым, когда детектор на кадр его потерял.
#
# Детектор может пропустить лицо в профиль или в тени, поэтому после размытия клип
# всё равно смотрит ИИ (stock.is_allowed): видно хоть одно лицо — клип не берём.
import os
import subprocess

_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets",
                      "face_detection_yunet_2023mar.onnx")
DETECT_WIDTH = 640     # детектор работает на уменьшенном кадре — быстро и достаточно точно
HOLD_FRAMES = 6        # сколько кадров держать рамку после пропажи лица


def _blur_box(frame, x, y, w, h):
    import cv2
    H, W = frame.shape[:2]
    cx, cy = x + w / 2, y + h / 2
    w, h = w * 1.6, h * 1.7  # с запасом: волосы, уши, подбородок
    x0, y0 = max(0, int(cx - w / 2)), max(0, int(cy - h / 2))
    x1, y1 = min(W, int(cx + w / 2)), min(H, int(cy + h / 2))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    roi = frame[y0:y1, x0:x1]
    small = cv2.resize(roi, (max(1, (x1 - x0) // 24), max(1, (y1 - y0) // 24)),
                       interpolation=cv2.INTER_LINEAR)
    roi = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    frame[y0:y1, x0:x1] = cv2.GaussianBlur(roi, (0, 0), 15)


def blur_video(src, dst, max_seconds=15.0):
    """Копия клипа (не длиннее max_seconds) с размытыми лицами.
    Возвращает число кадров, где были найдены лица (-1 — детектора нет, клип скопирован как есть:
    тогда открытые лица отсеет проверка ИИ)."""
    try:
        import cv2
    except ImportError:  # смена Actions, запущенная до установки opencv, подтянула новый код
        import shutil
        print("[TAMRA] opencv не установлен — лица не размываю, отсеет проверка ИИ")
        shutil.copy(src, dst)
        return -1
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not W or not H:
        raise RuntimeError(f"не читается видео {src}")
    scale = DETECT_WIDTH / W
    det = cv2.FaceDetectorYN.create(_MODEL, "", (DETECT_WIDTH, int(H * scale)), 0.5, 0.3, 5000)

    out = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{W}x{H}", "-r", f"{fps:.3f}", "-i", "-", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", dst],
        stdin=subprocess.PIPE)
    held, face_frames, n = [], 0, 0
    try:
        while n < max_seconds * fps:
            ok, frame = cap.read()
            if not ok:
                break
            n += 1
            _, found = det.detect(cv2.resize(frame, (DETECT_WIDTH, int(H * scale))))
            boxes = [] if found is None else [tuple(f[:4] / scale) for f in found]
            if boxes:
                face_frames += 1
            held = [(b, HOLD_FRAMES) for b in boxes] + [(b, t - 1) for b, t in held if t > 1]
            for (x, y, w, h), _ in held:
                _blur_box(frame, x, y, w, h)
            out.stdin.write(frame.tobytes())
    finally:
        cap.release()
        out.stdin.close()
        out.wait()
    if out.returncode != 0 or n == 0:
        raise RuntimeError("не получилось перекодировать клип с размытием")
    return face_frames
