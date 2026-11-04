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


import pytest  # noqa: E402

from repository import RepositoryError, re_safe_id  # noqa: E402


@pytest.fixture
def repository(tmp_path: Path) -> ReceiptRepository:
    return ReceiptRepository(tmp_path / "db.sqlite3", tmp_path / "images")


def test_images_are_stored_with_relative_paths(repository: ReceiptRepository):
    original, processed = repository.persist_images("abc-123", b"jpg-bytes", b"png-bytes", ".JPG")
    assert (original, processed) == ("abc-123_original.jpg", "abc-123_processed.png")
    assert repository.resolve_image_path(original).read_bytes() == b"jpg-bytes"
    assert repository.resolve_image_path(processed).read_bytes() == b"png-bytes"
    assert not list(repository.images_dir.glob(".*.tmp"))  # sin temporales huérfanos


def test_unknown_extension_falls_back_to_jpg(repository: ReceiptRepository):
    original, _ = repository.persist_images("abc", b"x", b"y", "gif")
    assert original.endswith(".jpg")


def test_database_survives_moving_the_data_folder(tmp_path: Path):
    first = ReceiptRepository(tmp_path / "a" / "db.sqlite3", tmp_path / "a" / "images")
    paths = first.persist_images("move-1", b"orig", b"proc", "png")
    first.save_receipt({**_record("move-1", "2026-10-20", "Tienda", 100), "image_path": paths[0], "processed_image_path": paths[1]})
    (tmp_path / "a").rename(tmp_path / "b")
    moved = ReceiptRepository(tmp_path / "b" / "db.sqlite3", tmp_path / "b" / "images")
    row = moved.list_receipts()[0]
    assert moved.resolve_image_path(row["image_path"]).read_bytes() == b"orig"


def test_legacy_absolute_paths_still_resolve(repository: ReceiptRepository, tmp_path: Path):
    legacy = tmp_path / "legacy.jpg"
    legacy.write_bytes(b"old")
    assert repository.resolve_image_path(str(legacy)) == legacy


def test_relative_paths_cannot_escape_images_dir(repository: ReceiptRepository):
    assert repository.resolve_image_path("../db.sqlite3") is None
    assert repository.resolve_image_path("") is None
    assert repository.resolve_image_path(None) is None


def test_remove_images_only_deletes_inside_images_dir(repository: ReceiptRepository, tmp_path: Path):
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"keep")
    inside, _ = repository.persist_images("rm-1", b"a", b"b", "jpg")
    repository.remove_images(str(outside), inside, None, "../outside.jpg")
    assert outside.exists()
    assert repository.resolve_image_path(inside).exists() is False


@pytest.mark.parametrize("bad", ["", "../../etc", "x" * 81, "///"])
def test_unsafe_source_ids_are_rejected(bad: str):
    if bad == "../../etc":
        assert re_safe_id(bad) == "etc"  # se filtran los caracteres peligrosos
    else:
        with pytest.raises(ValueError):
            re_safe_id(bad)


def test_find_by_source_id_and_get_receipt(repository: ReceiptRepository):
    receipt_id, _ = repository.save_receipt(_record("find-me", "2026-10-20", "Tienda", 500))
    assert repository.find_by_source_id("find-me") == receipt_id
    assert repository.find_by_source_id("missing") is None
    assert repository.get_receipt(receipt_id)["merchant"] == "Tienda"
    assert repository.get_receipt(999) is None


def test_non_positive_totals_are_rejected_by_database(repository: ReceiptRepository):
    with pytest.raises(RepositoryError):
        repository.save_receipt(_record("zero", "2026-10-20", "Tienda", 0))


def test_merchant_filter_escapes_like_wildcards(repository: ReceiptRepository):
    repository.save_receipt(_record("w1", "2026-10-20", "Tienda 100%", 100))
    repository.save_receipt(_record("w2", "2026-10-20", "Tienda 1000", 100))
    repository.save_receipt(_record("w3", "2026-10-20", "mi_tienda", 100))
    repository.save_receipt(_record("w4", "2026-10-20", "mixtienda", 100))
    assert [r["merchant"] for r in repository.list_receipts(merchant_query="100%")] == ["Tienda 100%"]
    assert [r["merchant"] for r in repository.list_receipts(merchant_query="i_t")] == ["mi_tienda"]
    assert len(repository.list_receipts(merchant_query="TIENDA")) == 4  # sin distinguir mayúsculas


def test_open_ended_date_filters_and_bounds(repository: ReceiptRepository):
    assert repository.date_bounds() == (None, None)
    for index, day in enumerate(["2026-01-05", "2026-03-10", "2026-12-31"]):
        repository.save_receipt(_record(f"d{index}", day, "Tienda", 100))
    assert repository.date_bounds() == ("2026-01-05", "2026-12-31")
    assert [r["receipt_date"] for r in repository.list_receipts(start_date="2026-03-10")] == ["2026-12-31", "2026-03-10"]
    assert [r["receipt_date"] for r in repository.list_receipts(end_date="2026-03-10")] == ["2026-03-10", "2026-01-05"]


def test_default_paths_follow_configured_data_dir():
    import app_config

    repository = ReceiptRepository()
    assert repository.database_path == app_config.DATABASE_PATH
    assert repository.database_path.is_file()
