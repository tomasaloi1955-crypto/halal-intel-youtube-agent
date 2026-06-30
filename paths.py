# paths.py — единое место для путей к состоянию.
# Локально DATA_DIR=".", на Render DATA_DIR="/data" (постоянный диск) — состояние переживает редеплой.
import os

DATA_DIR = os.getenv("DATA_DIR", ".")


def dpath(name):
    """Путь к файлу/папке состояния внутри DATA_DIR."""
    if DATA_DIR and DATA_DIR != ".":
        os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, name)
