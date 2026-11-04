"""Configuración común: cada prueba usa una carpeta de datos temporal y aislada."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Se fija antes de importar cualquier módulo de la app para que nunca toque ./data.
os.environ.setdefault("RECEIPT_DATA_DIR", tempfile.mkdtemp(prefix="boletas-tests-"))

import app_config  # noqa: E402

TEST_PASSWORD = "Clave-Segura-2026"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path):
    previous = app_config.DATA_DIR
    app_config.set_data_dir(tmp_path / "data")
    app_config.ensure_directories()
    try:
        import streamlit as st

        st.cache_resource.clear()
    except Exception:
        pass
    yield app_config.DATA_DIR
    app_config.set_data_dir(previous)


def make_receipt_png(lines: list[str], *, tilt_degrees: float = 0.0, size: tuple[int, int] = (900, 600)) -> bytes:
    """Genera una boleta sintética (texto negro sobre blanco) como PNG."""
    import cv2
    import numpy as np

    width, height = size
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)
    y = 60
    for text in lines:
        cv2.putText(canvas, text, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2, cv2.LINE_AA)
        y += 50
    if tilt_degrees:
        from ocr_service import _rotate_expand

        gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
        canvas = _rotate_expand(gray, tilt_degrees)
    ok, encoded = cv2.imencode(".png", canvas)
    assert ok
    return encoded.tobytes()


def ruled_image_png(tilt_degrees: float) -> bytes:
    """Imagen con renglones horizontales largos, ideal para medir la inclinación."""
    import cv2
    import numpy as np

    from ocr_service import _rotate_expand

    canvas = np.full((600, 800), 255, dtype=np.uint8)
    for y in range(80, 560, 40):
        cv2.line(canvas, (60, y), (740, y), 0, 3)
    if tilt_degrees:
        canvas = _rotate_expand(canvas, tilt_degrees)
    ok, encoded = cv2.imencode(".png", canvas)
    assert ok
    return encoded.tobytes()
