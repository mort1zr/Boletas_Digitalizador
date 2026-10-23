"""Configuración y rutas del prototipo."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
_configured_data_dir = os.getenv("RECEIPT_DATA_DIR", "").strip()
DATA_DIR = Path(_configured_data_dir).expanduser() if _configured_data_dir else BASE_DIR / "data"
if not DATA_DIR.is_absolute():
    DATA_DIR = (BASE_DIR / DATA_DIR).resolve()
IMAGES_DIR = DATA_DIR / "images"
DATABASE_PATH = DATA_DIR / "receipts.sqlite3"
USERS_PATH = DATA_DIR / "users.json"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
