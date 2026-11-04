"""Autenticación local con PBKDF2; nunca almacena contraseñas en texto plano."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import unicodedata
from pathlib import Path
from typing import Any

import app_config

PBKDF2_ITERATIONS = 600_000
MIN_USERNAME_LENGTH = 3
MIN_PASSWORD_LENGTH = 10


def _users_path(destination: Path | None) -> Path:
    # Se resuelve en cada llamada para respetar la configuración vigente (y las pruebas).
    return Path(destination) if destination is not None else app_config.USERS_PATH


def normalise_username(username: str) -> str:
    # NFC evita que "José" escrito con tilde combinada y con tilde precompuesta difieran.
    return unicodedata.normalize("NFC", username.strip())


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


def write_user(username: str, password: str, destination: Path | None = None) -> None:
    target = _users_path(destination)
    clean_username = normalise_username(username)
    if len(clean_username) < MIN_USERNAME_LENGTH:
        raise ValueError(f"El usuario debe tener al menos {MIN_USERNAME_LENGTH} caracteres.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Usa una contraseña de al menos {MIN_PASSWORD_LENGTH} caracteres.")
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {"username": clean_username, **password_record(password)}
    # Escritura atómica para evitar dejar un JSON incompleto si se interrumpe el proceso.
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def load_user(destination: Path | None = None) -> dict[str, Any] | None:
    target = _users_path(destination)
    if not target.is_file():
        return None
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
        required = {"username", "salt", "password_hash", "iterations", "algorithm"}
        if not isinstance(record, dict) or not required.issubset(record) or record["algorithm"] != "pbkdf2_hmac_sha256":
            return None
        return record
    except (OSError, ValueError, TypeError, KeyError):
        return None


def verify_login(username: str, password: str, destination: Path | None = None) -> bool:
    record = load_user(destination)
    if record is None or not password:
        return False
    # compare_digest con str solo admite ASCII; se comparan bytes UTF-8 para
    # que usuarios como "José" o "Muñoz" no provoquen TypeError.
    supplied = normalise_username(username).encode("utf-8")
    stored = normalise_username(str(record["username"])).encode("utf-8")
    if not hmac.compare_digest(supplied, stored):
        return False
    try:
        salt = bytes.fromhex(record["salt"])
        candidate = password_record(password, salt=salt, iterations=int(record["iterations"]))["password_hash"]
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.encode("ascii"), str(record["password_hash"]).encode("utf-8"))
