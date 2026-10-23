"""Autenticación local con PBKDF2; nunca almacena contraseñas en texto plano."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from pathlib import Path
from typing import Any

from app_config import USERS_PATH, ensure_directories

PBKDF2_ITERATIONS = 600_000


def password_record(password: str, *, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> dict[str, Any]:
    if not password:
        raise ValueError("La contraseña no puede estar vacía.")
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), actual_salt, iterations)
    return {
        "salt": actual_salt.hex(),
        "password_hash": digest.hex(),
        "iterations": iterations,
        "algorithm": "pbkdf2_hmac_sha256",
    }


def write_user(username: str, password: str, destination: Path = USERS_PATH) -> None:
    clean_username = username.strip()
    if len(clean_username) < 3:
        raise ValueError("El usuario debe tener al menos 3 caracteres.")
    if len(password) < 10:
        raise ValueError("Usa una contraseña de al menos 10 caracteres.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    record = {"username": clean_username, **password_record(password)}
    # Escritura atómica para evitar dejar un JSON incompleto si se interrumpe el proceso.
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
    temporary.replace(destination)


def load_user(destination: Path = USERS_PATH) -> dict[str, Any] | None:
    if not destination.is_file():
        return None
    try:
        record = json.loads(destination.read_text(encoding="utf-8"))
        required = {"username", "salt", "password_hash", "iterations", "algorithm"}
        if not required.issubset(record) or record["algorithm"] != "pbkdf2_hmac_sha256":
            return None
        return record
    except (OSError, ValueError, TypeError, KeyError):
        return None


def verify_login(username: str, password: str, destination: Path = USERS_PATH) -> bool:
    record = load_user(destination)
    if record is None or not password:
        return False
    if not hmac.compare_digest(username.strip(), str(record["username"])):
        return False
    try:
        salt = bytes.fromhex(record["salt"])
        candidate = password_record(password, salt=salt, iterations=int(record["iterations"]))["password_hash"]
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, str(record["password_hash"]))
