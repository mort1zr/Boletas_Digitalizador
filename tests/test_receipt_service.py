"""Flujo de revisión → guardado → consulta → CSV, sin interfaz."""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from receipt_service import (
    ReviewedFields,
    csv_bytes,
    date_from_input,
    format_total,
    money_from_input,
    save_reviewed_receipt,
    validate_review,
)
from repository import ReceiptRepository, RepositoryError


@pytest.fixture
def repository(tmp_path: Path) -> ReceiptRepository:
    return ReceiptRepository(tmp_path / "db.sqlite3", tmp_path / "images")


def _ocr_result(total: str = "118.00") -> dict:
    return {
        "raw_text": "TIENDA DEMO\nTOTAL S/ 118.00",
        "fields": {"receipt_date": "2026-10-21", "merchant": "TIENDA DEMO", "total": total, "warnings": []},
        "processed_png": b"\x89PNG-procesada",
    }


@pytest.mark.parametrize(
    ("raw", "cents", "has_error"),
    [
        ("45.90", 4590, False),
        ("45,9", 4590, False),
        ("S/ 1.234,50", 123450, False),
        ("1,234.50", 123450, False),
        ("1.234", 123400, False),
        ("0", None, True),
        ("-3", None, True),
        ("", None, True),
        (None, None, True),
        ("abc", None, True),
    ],
)
def test_money_from_input(raw, cents, has_error):
    value, error = money_from_input(raw)
    assert value == cents
    assert (error is not None) is has_error


@pytest.mark.parametrize(("raw", "ok"), [("2026-10-21", True), (" 2026-02-28 ", True), ("2026-02-30", False), ("21/10/2026", False), ("", False)])
def test_date_from_input(raw, ok):
    value, error = date_from_input(raw)
    assert (value is not None) is ok
    assert (error is None) is ok


def test_validate_review_collects_all_errors():
    reviewed, errors = validate_review("mal", "  ", "-1", False)
    assert reviewed is None
    assert len(errors) == 4


def test_validate_review_returns_clean_values():
    reviewed, errors = validate_review("2026-10-21", "  Tienda  ", "10,50", True)
    assert errors == []
    assert reviewed == ReviewedFields("2026-10-21", "Tienda", 1050)


def test_full_save_flow_keeps_proposed_and_confirmed_values(repository: ReceiptRepository):
    reviewed = ReviewedFields("2026-10-22", "Tienda Corregida", 12000)
    outcome = save_reviewed_receipt(
        repository, source_id="src-1", image_bytes=b"original-jpg", original_filename="foto.JPEG",
        ocr_result=_ocr_result(), reviewed=reviewed, receipt_format="A",
    )
    assert outcome.inserted is True
    record = repository.get_receipt(outcome.receipt_id)
    assert (record["receipt_date"], record["merchant"], record["total_cents"]) == ("2026-10-22", "Tienda Corregida", 12000)
    assert (record["proposed_date"], record["proposed_merchant"], record["proposed_total_cents"]) == ("2026-10-21", "TIENDA DEMO", 11800)
    assert record["original_ocr_text"].startswith("TIENDA DEMO")
    assert repository.resolve_image_path(record["image_path"]).read_bytes() == b"original-jpg"
    assert record["image_path"].endswith(".jpeg")
    assert repository.resolve_image_path(record["processed_image_path"]).read_bytes() == b"\x89PNG-procesada"


def test_missing_ocr_total_is_stored_as_null(repository: ReceiptRepository):
    outcome = save_reviewed_receipt(
        repository, source_id="src-null", image_bytes=b"x", original_filename="a.png",
        ocr_result=_ocr_result(total=""), reviewed=ReviewedFields("2026-10-22", "T", 100), receipt_format="B",
    )
    assert repository.get_receipt(outcome.receipt_id)["proposed_total_cents"] is None


def test_duplicate_save_does_not_touch_existing_evidence(repository: ReceiptRepository):
    kwargs = dict(source_id="dup-1", original_filename="a.jpg", ocr_result=_ocr_result(),
                  reviewed=ReviewedFields("2026-10-22", "Tienda", 100), receipt_format="A")
    first = save_reviewed_receipt(repository, image_bytes=b"primera", **kwargs)
    second = save_reviewed_receipt(repository, image_bytes=b"segunda", **kwargs)
    assert second.receipt_id == first.receipt_id
    assert second.inserted is False
    record = repository.get_receipt(first.receipt_id)
    # Antes del arreglo, el duplicado sobrescribía y luego BORRABA estas imágenes.
    assert repository.resolve_image_path(record["image_path"]).read_bytes() == b"primera"
    assert repository.resolve_image_path(record["processed_image_path"]).is_file()
    assert len(repository.list_receipts()) == 1


def test_race_where_insert_is_ignored_keeps_images(repository: ReceiptRepository, monkeypatch):
    # Simula que otra sesión insertó el mismo source_id entre la comprobación y el INSERT.
    monkeypatch.setattr(repository, "find_by_source_id", lambda source_id: None)
    monkeypatch.setattr(repository, "save_receipt", lambda record: (7, False))
    outcome = save_reviewed_receipt(
        repository, source_id="race", image_bytes=b"x", original_filename="a.jpg",
        ocr_result=_ocr_result(), reviewed=ReviewedFields("2026-10-22", "T", 100), receipt_format="A",
    )
    assert outcome.receipt_id == 7 and outcome.inserted is False
    assert (repository.images_dir / "race_original.jpg").is_file()


def test_failed_insert_cleans_up_orphan_images(repository: ReceiptRepository, monkeypatch):
    def boom(record):
        raise RepositoryError("disco lleno")

    monkeypatch.setattr(repository, "save_receipt", boom)
    with pytest.raises(RepositoryError):
        save_reviewed_receipt(
            repository, source_id="fail-1", image_bytes=b"x", original_filename="a.jpg",
            ocr_result=_ocr_result(), reviewed=ReviewedFields("2026-10-22", "T", 100), receipt_format="A",
        )
    assert list(repository.images_dir.iterdir()) == []


def test_csv_export_has_headers_bom_two_decimals_and_formula_protection():
    rows = [
        {"id": 1, "receipt_date": "2026-10-21", "merchant": "=HYPERLINK(\"x\")", "total_cents": 11800},
        {"id": 2, "receipt_date": "2026-10-20", "merchant": "Tienda, \"La Buena\"", "total_cents": 5},
        {"id": 3, "receipt_date": "2026-10-19", "merchant": "\t+cmd", "total_cents": 100000},
        {"id": 4, "receipt_date": "2026-10-18", "merchant": "José Muñoz", "total_cents": 1},
    ]
    payload = csv_bytes(rows)
    assert payload.startswith(b"\xef\xbb\xbf")
    parsed = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    assert parsed[0] == ["id", "fecha", "comercio", "total"]
    assert parsed[1] == ["1", "2026-10-21", "'=HYPERLINK(\"x\")", "118.00"]
    assert parsed[2] == ["2", "2026-10-20", "Tienda, \"La Buena\"", "0.05"]
    assert parsed[3][2] == "'\t+cmd"
    assert parsed[3][3] == "1000.00"
    assert parsed[4][2] == "José Muñoz"


def test_csv_with_no_rows_has_only_header():
    assert csv_bytes([]).decode("utf-8-sig").strip() == "id,fecha,comercio,total"


def test_format_total():
    assert format_total(None) == "No detectado"
    assert format_total(1050) == "10.50"
