"""Pruebas de la interfaz Streamlit con AppTest (sin navegador).

Cubren login, cierre de sesión, consulta con filtros, evidencia y exportación.
La carga de archivos no está soportada por AppTest; ese flujo se valida en
test_receipt_service.py (validación + guardado) y test_ocr_service.py (OCR).
"""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from auth_service import write_user
from conftest import TEST_PASSWORD, make_receipt_png
from repository import ReceiptRepository


def _app() -> None:
    from ui import render_app

    render_app()


def _new_app() -> AppTest:
    return AppTest.from_function(_app, default_timeout=30)


def _texts(at: AppTest) -> str:
    parts = []
    for kind in ("markdown", "caption", "info", "warning", "error", "success", "title", "subheader", "code", "text"):
        parts.extend(str(element.value) for element in getattr(at, kind))
    return "\n".join(parts)


def _login(at: AppTest, username: str = "operador", password: str = TEST_PASSWORD) -> AppTest:
    at.run()
    at.text_input[0].input(username)
    at.text_input[1].input(password)
    at.button[0].click().run()
    return at


@pytest.fixture
def account():
    write_user("operador", TEST_PASSWORD)


@pytest.fixture
def seeded():
    repository = ReceiptRepository()
    rows = [
        ("s1", "2026-10-20", "Mercado Norte", 1234),
        ("s2", "2026-10-21", "Mercado Sur", 4567),
        ("s3", "2026-09-01", "Farmacia Central", 990),
    ]
    for source_id, day, merchant, cents in rows:
        png = make_receipt_png([merchant], size=(300, 120))
        paths = repository.persist_images(source_id, png, png, "png")
        repository.save_receipt({
            "receipt_date": day, "merchant": merchant, "total_cents": cents,
            "image_path": paths[0], "processed_image_path": paths[1],
            "original_ocr_text": f"{merchant}\nTOTAL", "proposed_date": day,
            "proposed_merchant": merchant.upper(), "proposed_total_cents": None,
            "receipt_format": "A", "source_id": source_id,
        })
    return repository


def test_without_account_shows_setup_instructions():
    at = _new_app()
    at.run()
    assert not at.exception
    assert "create_user.py" in _texts(at)
    assert len(at.text_input) == 0


def test_wrong_password_is_rejected(account):
    at = _login(_new_app(), password="clave-incorrecta")
    assert not at.exception
    assert any("No se pudo iniciar sesión" in e.value for e in at.error)
    assert at.session_state["authenticated"] is False


def test_non_ascii_user_can_log_in():
    write_user("José", TEST_PASSWORD)
    at = _login(_new_app(), username="José")
    assert not at.exception
    assert at.session_state["authenticated"] is True


def test_login_shows_both_tabs_and_logout_returns_to_login(account):
    at = _login(_new_app())
    assert not at.exception
    assert at.session_state["authenticated"] is True
    assert [tab.label for tab in at.tabs] == ["📷 Cargar y revisar", "📊 Consultar registros"]
    assert "Selecciona una imagen para comenzar." in _texts(at)
    logout = next(b for b in at.sidebar.button if b.label == "Cerrar sesión")
    logout.click().run()
    assert at.session_state["authenticated"] is False
    assert "Iniciar sesión" in _texts(at)


def test_dashboard_lists_all_records_newest_first_by_default(account, seeded):
    at = _login(_new_app())
    assert not at.exception
    frame = at.dataframe[0].value
    assert list(frame["Fecha"]) == ["2026-10-21", "2026-10-20", "2026-09-01"]
    assert list(frame["Total"]) == ["45.67", "12.34", "9.90"]
    assert "3 registro(s)" in _texts(at)
    assert "2026-09-01 a 2026-10-21" in _texts(at)


def test_record_saved_after_filters_were_set_is_still_visible(account, seeded):
    at = _login(_new_app())
    seeded.save_receipt({
        "receipt_date": "2027-01-15", "merchant": "Tienda Nueva", "total_cents": 500,
        "image_path": "x.jpg", "original_ocr_text": "", "receipt_format": "A", "source_id": "nuevo",
    })
    at.run()
    assert "2027-01-15" in list(at.dataframe[0].value["Fecha"])


def test_merchant_and_date_filters_combine(account, seeded):
    import datetime as dt

    at = _login(_new_app())
    at.text_input(key="filter_merchant").input("mercado").run()
    assert list(at.dataframe[0].value["Comercio"]) == ["Mercado Sur", "Mercado Norte"]
    at.date_input(key="filter_start_date").set_value(dt.date(2026, 10, 21)).run()
    assert list(at.dataframe[0].value["Comercio"]) == ["Mercado Sur"]
    at.text_input(key="filter_merchant").input("farmacia").run()
    assert len(at.dataframe) == 0
    assert "No hay registros para los filtros seleccionados." in _texts(at)


def test_inverted_date_range_shows_error(account, seeded):
    import datetime as dt

    at = _login(_new_app())
    at.date_input(key="filter_start_date").set_value(dt.date(2026, 12, 1))
    at.date_input(key="filter_end_date").set_value(dt.date(2026, 1, 1)).run()
    assert any("rango de fechas está invertido" in e.value for e in at.error)


def test_evidence_shows_proposed_and_confirmed_values(account, seeded):
    at = _login(_new_app())
    receipt_id = seeded.find_by_source_id("s2")
    at.session_state["selected_receipt_id"] = receipt_id
    at.run()
    assert not at.exception
    text = _texts(at)
    assert f"Evidencia del registro ID {receipt_id}" in text
    assert "Comercio: MERCADO SUR" in text  # propuesto por OCR
    assert "Comercio: Mercado Sur" in text  # confirmado
    assert "Total: No detectado" in text
    assert "Total: 45.67" in text
    assert "La imagen original ya no está disponible" not in text


def test_evidence_warns_when_image_file_is_missing(account, seeded):
    receipt_id = seeded.find_by_source_id("s1")
    seeded.resolve_image_path(seeded.get_receipt(receipt_id)["image_path"]).unlink()
    at = _login(_new_app())
    at.session_state["selected_receipt_id"] = receipt_id
    at.run()
    assert not at.exception
    assert "La imagen original ya no está disponible" in _texts(at)


def test_empty_database_shows_info(account):
    at = _login(_new_app())
    assert "No hay registros para los filtros seleccionados." in _texts(at)


def test_corrupt_archived_image_shows_warning_instead_of_crashing(account, seeded):
    receipt_id = seeded.find_by_source_id("s3")
    seeded.resolve_image_path(seeded.get_receipt(receipt_id)["image_path"]).write_bytes(b"no es imagen")
    at = _login(_new_app())
    at.session_state["selected_receipt_id"] = receipt_id
    at.run()
    assert not at.exception
    assert "No se pudo abrir la imagen archivada" in _texts(at)
    assert "Evidencia del registro ID" in _texts(at)
