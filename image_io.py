"""Normaliza las fotos que sube el usuario a un formato que el resto del sistema entiende.

Los celulares modernos guardan las fotos en HEIC/HEIF por defecto (iPhone desde iOS 11 y
varios Samsung Galaxy). Una persona corriente no sabe qué es ese formato, así que el sistema
lo acepta tal cual y lo convierte a JPEG al subirlo: ni hay que cambiar ajustes de la cámara
ni usar un conversor. La rotación indicada por la cámara (EXIF) se aplica al convertir.
"""
from __future__ import annotations

import io
from pathlib import Path

HEIC_EXTENSIONS = {".heic", ".heif"}
_MARCAS_HEIF = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}
JPEG_QUALITY = 92
MAX_SIDE = 3200  # el OCR trabaja a 2400 px; así la copia convertida no supera el límite de 10 MB


def is_heif(content: bytes, filename: str = "") -> bool:
    """Detecta HEIC/HEIF por su firma (caja ``ftyp``), no solo por la extensión."""
    if len(content) >= 12 and content[4:8] == b"ftyp" and content[8:12] in _MARCAS_HEIF:
        return True
    return Path(filename or "").suffix.lower() in HEIC_EXTENSIONS and content[4:8] == b"ftyp"


def to_supported_image(content: bytes, filename: str = "") -> tuple[bytes, str]:
    """Devuelve (bytes, nombre) en JPG/PNG. HEIC/HEIF se convierte; lo demás pasa sin cambios.

    Lanza ``ValueError`` con un mensaje claro si el archivo HEIC está dañado.
    """
    if not is_heif(content, filename):
        return content, filename
    try:
        from PIL import Image, ImageOps
        from pillow_heif import register_heif_opener

        register_heif_opener()
        with Image.open(io.BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((MAX_SIDE, MAX_SIDE))  # solo reduce, nunca amplía
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=JPEG_QUALITY)
    except Exception as exc:
        raise ValueError("No se pudo leer la foto HEIC. Prueba con otra o tómala de nuevo.") from exc
    stem = Path(filename or "foto").stem or "foto"
    return output.getvalue(), f"{stem}.jpg"
