"""Lectura de fotos HEIC/HEIF (iPhone y Samsung) y su conversión a JPG."""
from __future__ import annotations

import io

import cv2
import numpy as np
import pytest
from PIL import Image
from pillow_heif import from_pillow, register_heif_opener

import image_io
from conftest import make_receipt_png
from ocr_service import preprocess_image

register_heif_opener()


def _heic_bytes(size=(900, 600), orientation: int | None = None) -> bytes:
    image = Image.open(io.BytesIO(make_receipt_png(["TOTAL S/ 45.90"], size=size))).convert("RGB")
    heif = from_pillow(image)
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        heif.info["exif"] = exif.tobytes()
    out = io.BytesIO()
    heif.save(out, format="HEIF", quality=90)
    return out.getvalue()


def test_heic_se_detecta_por_firma_aunque_la_extension_sea_otra():
    assert image_io.is_heif(_heic_bytes(), "foto.jpg")
    assert not image_io.is_heif(make_receipt_png(["x"]), "foto.heic")


def test_heic_se_convierte_a_jpg_decodificable():
    contenido, nombre = image_io.to_supported_image(_heic_bytes(), "IMG_0001.HEIC")
    assert nombre == "IMG_0001.jpg"
    assert contenido[:3] == b"\xff\xd8\xff"
    assert cv2.imdecode(np.frombuffer(contenido, np.uint8), cv2.IMREAD_COLOR).shape[:2] == (600, 900)


def test_heic_pasa_por_el_preprocesado_del_ocr():
    contenido, _ = image_io.to_supported_image(_heic_bytes(), "a.heic")
    assert preprocess_image(contenido).png_bytes


def test_se_aplica_la_rotacion_de_la_camara():
    contenido, _ = image_io.to_supported_image(_heic_bytes(orientation=6), "a.heic")
    alto, ancho = cv2.imdecode(np.frombuffer(contenido, np.uint8), cv2.IMREAD_COLOR).shape[:2]
    assert (alto, ancho) == (900, 600)  # la foto de 900x600 con orientación 6 queda vertical


def test_foto_grande_se_reduce():
    contenido, _ = image_io.to_supported_image(_heic_bytes(size=(4000, 3000)), "a.heic")
    assert max(cv2.imdecode(np.frombuffer(contenido, np.uint8), cv2.IMREAD_COLOR).shape[:2]) == image_io.MAX_SIDE


def test_jpg_y_png_no_se_tocan():
    png = make_receipt_png(["x"])
    assert image_io.to_supported_image(png, "a.png") == (png, "a.png")


def test_heic_danado_da_mensaje_claro():
    falso = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 40
    with pytest.raises(ValueError, match="HEIC"):
        image_io.to_supported_image(falso, "a.heic")
