"""Configuración y rutas del prototipo."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _resolve_data_dir(raw: str | os.PathLike[str] | None) -> Path:
    value = str(raw or "").strip()
    path = Path(value).expanduser() if value else BASE_DIR / "data"
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()
    return path


DATA_DIR = _resolve_data_dir(os.getenv("RECEIPT_DATA_DIR"))
IMAGES_DIR = DATA_DIR / "images"
DATABASE_PATH = DATA_DIR / "receipts.sqlite3"
USERS_PATH = DATA_DIR / "users.json"


def set_data_dir(path: str | os.PathLike[str]) -> None:
    """Redirige todas las rutas de datos (útil para pruebas o despliegues)."""
    global DATA_DIR, IMAGES_DIR, DATABASE_PATH, USERS_PATH
    DATA_DIR = _resolve_data_dir(path)
    IMAGES_DIR = DATA_DIR / "images"
    DATABASE_PATH = DATA_DIR / "receipts.sqlite3"
    USERS_PATH = DATA_DIR / "users.json"


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
