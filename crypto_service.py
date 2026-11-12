"""Cifrado en reposo de las imágenes y del texto OCR (Fernet: AES-128-CBC + HMAC-SHA256).

Qué se cifra: las fotografías (original y procesada) y el texto OCR completo, que es donde
puede quedar información personal. Qué no: fecha, comercio y total, porque las consultas
(filtros, CSV y preguntas en lenguaje natural) los necesitan en claro.

Dónde está la clave, en orden de preferencia:
1. Variable de entorno ``RECEIPT_ENCRYPTION_KEY`` (clave Fernet en base64). Es la opción
   recomendada: la clave queda fuera de la carpeta de datos, así que copiar ``data/`` no basta
   para leer las boletas. En Docker u hospedaje, guárdala como secreto.
2. Archivo ``.secret.key`` dentro de la carpeta de datos (se crea solo, con permisos 0600). Es
   cómodo para uso local, pero quien copie toda la carpeta de datos se lleva también la clave.

Si se pierde la clave, los datos cifrados no se pueden recuperar. Los registros anteriores al
cifrado (en texto plano) se siguen leyendo con normalidad.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

import app_config

ENV_KEY = "RECEIPT_ENCRYPTION_KEY"
KEY_FILENAME = ".secret.key"
PREFIJO_TEXTO = "enc:v1:"
_PREFIJO_TOKEN = b"gAAAAA"  # todo token Fernet comienza así (versión 0x80 + marca de tiempo)


class DecryptionError(RuntimeError):
    """El dato está cifrado pero no se pudo descifrar (clave incorrecta o dato dañado)."""


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")


def _key_file() -> Path:
    return app_config.DATA_DIR / KEY_FILENAME


def _load_key() -> bytes:
    configured = os.getenv(ENV_KEY, "").strip()
    if configured:
        return configured.encode("ascii")
    path = _key_file()
    if path.is_file():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    # 'x' evita pisar una clave creada en paralelo por otro proceso.
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_bytes().strip()
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(key)
    return key


def _fernet() -> Fernet:
    try:
        return Fernet(_load_key())
    except (ValueError, TypeError) as exc:
        raise DecryptionError(
            f"La clave de cifrado no es válida. Genera una con `python -c \"import crypto_service; "
            f"print(crypto_service.generate_key())\"` y guárdala en {ENV_KEY}."
        ) from exc


def is_encrypted_bytes(payload: bytes) -> bool:
    return payload.startswith(_PREFIJO_TOKEN)


def encrypt_bytes(payload: bytes) -> bytes:
    return _fernet().encrypt(payload)


def decrypt_bytes(payload: bytes) -> bytes:
    """Descifra; si el dato es anterior al cifrado (texto plano), lo devuelve igual."""
    if not is_encrypted_bytes(payload):
        return payload
    try:
        return _fernet().decrypt(payload)
    except InvalidToken as exc:
        raise DecryptionError("No se pudo descifrar el archivo: clave incorrecta o contenido dañado.") from exc


def encrypt_text(texto: str) -> str:
    if not texto:
        return texto
    return PREFIJO_TEXTO + _fernet().encrypt(texto.encode("utf-8")).decode("ascii")


def decrypt_text(valor: str | None) -> str | None:
    if valor is None or not valor.startswith(PREFIJO_TEXTO):
        return valor  # vacío o registro anterior al cifrado
    try:
        return _fernet().decrypt(valor[len(PREFIJO_TEXTO):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError("No se pudo descifrar el texto OCR: clave incorrecta o contenido dañado.") from exc
