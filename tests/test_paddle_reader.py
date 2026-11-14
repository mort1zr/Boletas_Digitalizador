"""Adaptador de PaddleOCR: formato de salida y una prueba de humo con los modelos reales (si existen)."""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import pytest

import ocr_service
from conftest import make_receipt_png


class _FakeEngine:
    def __init__(self, pages):
        self.pages, self.seen = pages, None

    def predict(self, image):
        self.seen = image
        return self.pages


def _page():
    return {
        "rec_polys": [np.array([[10, 10], [200, 10], [200, 40], [10, 40]]), np.array([[10, 60], [200, 60], [200, 90], [10, 90]])],
        "rec_texts": ["TIENDA S.A.C.", "TOTAL S/ 45.90"],
        "rec_scores": [0.98, np.float32(0.95)],
    }


def test_el_adaptador_devuelve_caja_texto_y_confianza():
    engine = _FakeEngine([_page()])
    items = ocr_service.PaddleReader(engine).read(np.full((100, 220), 255, np.uint8))
    assert [i[1] for i in items] == ["TIENDA S.A.C.", "TOTAL S/ 45.90"]
    assert all(isinstance(i[2], float) for i in items)
    assert items[0][0] == [[10.0, 10.0], [200.0, 10.0], [200.0, 40.0], [10.0, 40.0]]


def test_el_adaptador_entrega_imagen_de_tres_canales():
    engine = _FakeEngine([_page()])
    ocr_service.PaddleReader(engine).read(np.full((100, 220), 255, np.uint8))  # gris de entrada
    assert engine.seen.ndim == 3 and engine.seen.shape[2] == 3


def test_run_ocr_agrupa_las_cajas_en_lineas(monkeypatch):
    monkeypatch.setattr(ocr_service, "_reader", lambda: ocr_service.PaddleReader(_FakeEngine([_page()])))
    lines, raw = ocr_service.run_ocr(np.full((100, 220), 255, np.uint8))
    assert raw == "TIENDA S.A.C.\nTOTAL S/ 45.90"
    assert lines[1].confidence == pytest.approx(0.95)


def test_run_ocr_sin_texto_falla_con_mensaje_claro(monkeypatch):
    monkeypatch.setattr(ocr_service, "_reader", lambda: ocr_service.PaddleReader(_FakeEngine([{"rec_polys": [], "rec_texts": [], "rec_scores": []}])))
    with pytest.raises(RuntimeError, match="no reconoció texto"):
        ocr_service.run_ocr(np.full((50, 50), 255, np.uint8))


def test_sin_paddleocr_instalado_el_error_es_claro(monkeypatch):
    import builtins
    import sys

    ocr_service._reader.cache_clear()
    monkeypatch.delitem(sys.modules, "paddleocr", raising=False)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "paddleocr":
            raise ImportError("simulado")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="PaddleOCR no está instalado"):
        ocr_service._reader()
    ocr_service._reader.cache_clear()


_MODELOS = os.environ.get("PADDLE_MODELOS", "")


@pytest.mark.skipif(
    not (_MODELOS and Path(_MODELOS, f"{ocr_service.DETECTION_MODEL}_infer").is_dir()),
    reason="requiere paddleocr y los modelos locales en PADDLE_MODELOS",
)
def test_humo_con_modelos_reales():
    """Lee texto de verdad: solo corre donde PaddleOCR y sus modelos están disponibles."""
    ocr_service._reader.cache_clear()
    imagen = make_receipt_png(["TIENDA LOS ANDES S.A.C.", "TOTAL A PAGAR S/ 118.00"], size=(1000, 300))
    gris = cv2.cvtColor(cv2.imdecode(np.frombuffer(imagen, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY)
    _, texto = ocr_service.run_ocr(gris)
    assert "118.00" in texto.replace(" ", "")
