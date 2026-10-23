from pathlib import Path

from repository import ReceiptRepository


def _record(source_id: str, receipt_date: str, merchant: str, total_cents: int):
    return {
        "receipt_date": receipt_date,
        "merchant": merchant,
        "total_cents": total_cents,
        "image_path": "/tmp/original.jpg",
        "processed_image_path": "/tmp/processed.png",
        "original_ocr_text": "OCR de prueba",
        "proposed_date": receipt_date,
        "proposed_merchant": merchant,
        "proposed_total_cents": total_cents,
        "receipt_format": "A",
        "source_id": source_id,
    }


def test_save_is_idempotent_for_same_submission_and_filters_are_inclusive(tmp_path: Path):
    repository = ReceiptRepository(tmp_path / "test.sqlite3", tmp_path / "images")
    first_id, inserted = repository.save_receipt(_record("submission-1", "2026-10-20", "Mercado Norte", 1234))
    assert inserted is True
    second_id, inserted_again = repository.save_receipt(_record("submission-1", "2026-10-20", "Mercado Norte", 1234))
    assert second_id == first_id
    assert inserted_again is False

    repository.save_receipt(_record("submission-2", "2026-10-21", "Mercado Sur", 4567))
    repository.save_receipt(_record("submission-3", "2026-10-19", "Tienda Uno", 7890))
    rows = repository.list_receipts("2026-10-20", "2026-10-21", "Mercado")
    assert [row["receipt_date"] for row in rows] == ["2026-10-21", "2026-10-20"]
    assert [row["merchant"] for row in rows] == ["Mercado Sur", "Mercado Norte"]
    assert rows[0]["total_cents"] == 4567
