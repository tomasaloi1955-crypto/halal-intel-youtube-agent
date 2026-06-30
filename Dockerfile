FROM python:3.11-slim

# ffmpeg — для монтажа видео; шрифты DejaVu — для подписей и обложек (кириллица)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chromium для рендера обложек (HTML/CSS → PNG через Playwright)
RUN python -m playwright install --with-deps chromium
COPY . .

# Состояние (очередь, токен, озвучки, seen) хранится в /data — это постоянный диск Render
ENV DATA_DIR=/data

CMD ["python", "main.py"]
