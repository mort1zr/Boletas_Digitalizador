"""Flujo completo en la interfaz: imagen (archivo o cámara) → OCR → revisión → guardado.

EasyOCR se sustituye por un lector simulado; el resto (Streamlit, OpenCV, SQLite y
almacenamiento de imágenes) se ejecuta de verdad.
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

import ocr_service
from auth_service import write_user
from conftest import TEST_PASSWORD
from repository import ReceiptRepository
from ui import SOURCE_CAMERA, SOURCE_FILE


def _app() -> None:
    from ui import render_app

    render_app()


def _box(x, y, w=200, h=24):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


class _FakeReader:
    def __init__(self):
        self.calls = 0

    def readtext(self, image, **kwargs):
        self.calls += 1
        return [
            (_box(20, 20), "BODEGA SAN JUAN", 0.95),
            (_box(20, 60), "Fecha: 21/10/2026", 0.93),
            (_box(20, 100), "SUBTOTAL S/ 40.00", 0.9),
            (_box(20, 140), "TOTAL A PAGAR S/ 47.20", 0.94),
        ]


@pytest.fixture
def reader(monkeypatch):
    fake = _FakeReader()
    monkeypatch.setattr(ocr_service, "_reader", lambda: fake)
    return fake


def _photo(ext: str = ".jpg") -> bytes:
    canvas = np.full((480, 640, 3), 255, dtype=np.uint8)
    cv2.putText(canvas, "BODEGA SAN JUAN", (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    cv2.putText(canvas, "TOTAL A PAGAR S/ 47.20", (30, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    ok, encoded = cv2.imencode(ext, canvas)
    assert ok
    return encoded.tobytes()


def _logged_in_app() -> AppTest:
    write_user("operador", TEST_PASSWORD)
    at = AppTest.from_function(_app, default_timeout=60)
    at.run()
    at.text_input[0].input("operador")
    at.text_input[1].input(TEST_PASSWORD)
    at.button[0].click().run()
    assert at.session_state["authenticated"] is True
    return at


def _texts(at: AppTest) -> str:
    parts = []
    for kind in ("markdown", "caption", "info", "warning", "error", "success"):
        parts.extend(str(element.value) for element in getattr(at, kind))
    return "\n".join(parts)


def _review_input(at: AppTest, label: str):
    return next(widget for widget in at.text_input if widget.label == label)


def _process(at: AppTest) -> AppTest:
    at.button(key="process_receipt_button").click().run()
    assert not at.exception
    assert not at.session_state["ocr_error"], at.session_state["ocr_error"]
    return at


def _confirm_and_save(at: AppTest) -> AppTest:
    next(c for c in at.checkbox if c.label.startswith("Confirmo")).check()
    next(b for b in at.button if b.label == "Guardar registro confirmado").click().run()
    assert not at.exception
    return at


def test_file_source_is_the_default_and_camera_is_offered(reader):
    at = _logged_in_app()
    assert at.radio(key="image_source").value == SOURCE_FILE
    assert at.radio(key="image_source").options == [SOURCE_FILE, SOURCE_CAMERA]
    assert len(at.camera_input) == 0
    assert "Selecciona una imagen o toma una foto para comenzar." in _texts(at)


def test_camera_capture_full_flow_saves_confirmed_record(reader):
    at = _logged_in_app()
    at.radio(key="image_source").set_value(SOURCE_CAMERA).run()
    assert len(at.camera_input) == 1
    assert len(at.file_uploader) == 0
    assert "Foto tomada con la cámara" not in _texts(at)

    at.camera_input(key="receipt_camera").upload("image.jpg", _photo()).run()
    assert not at.exception
    _process(at)
    assert reader.calls == 1

    # Los candidatos OCR llegan prellenados al formulario de revisión.
    assert _review_input(at, "Fecha (AAAA-MM-DD)").value == "2026-10-21"
    assert _review_input(at, "Comercio").value == "BODEGA SAN JUAN"
    assert _review_input(at, "Total").value == "47.20"

    _review_input(at, "Comercio").input("Bodega San Juan")  # corrección manual
    _confirm_and_save(at)
    assert any("Registro guardado correctamente" in s.value for s in at.success)

    rows = ReceiptRepository().list_receipts()
    assert len(rows) == 1
    record = rows[0]
    assert (record["receipt_date"], record["merchant"], record["total_cents"]) == ("2026-10-21", "Bodega San Juan", 4720)
    assert record["proposed_merchant"] == "BODEGA SAN JUAN"
    assert record["image_path"].endswith("_original.jpg")
    stored = ReceiptRepository().resolve_image_path(record["image_path"]).read_bytes()
    assert stored == _photo()  # la foto original se archiva sin modificar

    # Volver a pulsar Guardar no crea otra fila.
    _confirm_and_save(at)
    assert "ya se guardó" in _texts(at)
    assert len(ReceiptRepository().list_receipts()) == 1


def test_new_camera_photo_starts_a_new_record(reader):
    at = _logged_in_app()
    at.radio(key="image_source").set_value(SOURCE_CAMERA).run()
    at.camera_input(key="receipt_camera").upload("image.jpg", _photo()).run()
    _process(at)
    _confirm_and_save(at)
    first_source = at.session_state["active_source_id"]

    canvas = cv2.imdecode(np.frombuffer(_photo(), np.uint8), cv2.IMREAD_COLOR)
    canvas[0:5, 0:5] = 0
    other = cv2.imencode(".jpg", canvas)[1].tobytes()
    at.camera_input(key="receipt_camera").upload("image.jpg", other).run()
    assert at.session_state["active_source_id"] != first_source
    assert at.session_state["ocr_result"] is None  # el resultado anterior no se reutiliza
    _process(at)
    _confirm_and_save(at)
    assert len(ReceiptRepository().list_receipts()) == 2


def test_saving_requires_explicit_confirmation(reader):
    at = _logged_in_app()
    at.radio(key="image_source").set_value(SOURCE_CAMERA).run()
    at.camera_input(key="receipt_camera").upload("image.jpg", _photo()).run()
    _process(at)
    next(b for b in at.button if b.label == "Guardar registro confirmado").click().run()
    assert any("confirmación explícita" in e.value for e in at.error)
    assert ReceiptRepository().list_receipts() == []


def test_clearing_the_photo_resets_the_work(reader):
    at = _logged_in_app()
    at.radio(key="image_source").set_value(SOURCE_CAMERA).run()
    at.camera_input(key="receipt_camera").upload("image.jpg", _photo()).run()
    _process(at)
    at.camera_input(key="receipt_camera").clear().run()
    assert at.session_state["ocr_result"] is None
    assert "Selecciona una imagen o toma una foto para comenzar." in _texts(at)


def test_uploaded_png_full_flow_keeps_png_extension(reader):
    at = _logged_in_app()
    at.file_uploader(key="receipt_uploader").upload("boleta.png", _photo(".png"), "image/png").run()
    assert not at.exception
    _process(at)
    _confirm_and_save(at)
    record = ReceiptRepository().list_receipts()[0]
    assert record["image_path"].endswith("_original.png")


def test_corrupt_upload_is_rejected_before_ocr(reader):
    at = _logged_in_app()
    at.file_uploader(key="receipt_uploader").upload("boleta.jpg", b"esto no es una imagen", "image/jpeg").run()
    assert not at.exception
    assert any("no contiene una imagen" in e.value for e in at.error)
    assert reader.calls == 0


def test_camera_requests_high_resolution_when_supported(monkeypatch):
    import ui

    def with_resolution(label, key=None, *, resolution=None):
        return None

    def without_resolution(label, key=None):
        return None

    monkeypatch.setattr(ui.st, "camera_input", with_resolution)
    assert ui._camera_options() == {"resolution": "1080p"}
    monkeypatch.setattr(ui.st, "camera_input", without_resolution)
    assert ui._camera_options() == {}
