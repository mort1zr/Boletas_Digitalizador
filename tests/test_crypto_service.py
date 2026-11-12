from pathlib import Path

import pytest

import app_config
import crypto_service
from crypto_service import DecryptionError
from receipt_service import ReviewedFields, save_reviewed_receipt
from repository import ReceiptRepository


@pytest.fixture(autouse=True)
def sin_clave_en_entorno(monkeypatch):
    monkeypatch.delenv(crypto_service.ENV_KEY, raising=False)


def test_bytes_roundtrip_and_ciphertext_differs():
    token = crypto_service.encrypt_bytes(b"foto-privada")
    assert token != b"foto-privada" and crypto_service.is_encrypted_bytes(token)
    assert crypto_service.decrypt_bytes(token) == b"foto-privada"


def test_text_roundtrip_and_prefix():
    cifrado = crypto_service.encrypt_text("TOTAL S/ 10.00")
    assert cifrado.startswith(crypto_service.PREFIJO_TEXTO) and "TOTAL" not in cifrado
    assert crypto_service.decrypt_text(cifrado) == "TOTAL S/ 10.00"


def test_empty_and_legacy_values_pass_through():
    assert crypto_service.encrypt_text("") == ""
    assert crypto_service.decrypt_text(None) is None
    assert crypto_service.decrypt_text("texto antiguo en claro") == "texto antiguo en claro"
    assert crypto_service.decrypt_bytes(b"\xff\xd8\xff jpg antiguo") == b"\xff\xd8\xff jpg antiguo"


def test_key_file_is_created_once_with_private_permissions():
    crypto_service.encrypt_text("a")
    clave = app_config.DATA_DIR / crypto_service.KEY_FILENAME
    assert clave.is_file() and (clave.stat().st_mode & 0o077) == 0
    primera = clave.read_bytes()
    crypto_service.encrypt_text("b")
    assert clave.read_bytes() == primera


def test_environment_key_takes_precedence_and_avoids_key_file(monkeypatch):
    monkeypatch.setenv(crypto_service.ENV_KEY, crypto_service.generate_key())
    token = crypto_service.encrypt_bytes(b"dato")
    assert not (app_config.DATA_DIR / crypto_service.KEY_FILENAME).exists()
    assert crypto_service.decrypt_bytes(token) == b"dato"


def test_wrong_key_raises_clear_error(monkeypatch):
    monkeypatch.setenv(crypto_service.ENV_KEY, crypto_service.generate_key())
    token = crypto_service.encrypt_bytes(b"dato")
    monkeypatch.setenv(crypto_service.ENV_KEY, crypto_service.generate_key())
    with pytest.raises(DecryptionError):
        crypto_service.decrypt_bytes(token)


def test_invalid_key_in_environment_is_reported(monkeypatch):
    monkeypatch.setenv(crypto_service.ENV_KEY, "no-es-una-clave")
    with pytest.raises(DecryptionError, match="no es válida"):
        crypto_service.encrypt_text("x")


# --- Integración con el repositorio -------------------------------------------------------------
def _guardar(repo: ReceiptRepository, texto_ocr: str = "TIENDA\nCliente: DNI 79360747\nTOTAL S/ 10.00") -> int:
    resultado = {"raw_text": texto_ocr, "fields": {"receipt_date": "2026-10-21", "merchant": "TIENDA", "total": "10.00"},
                 "processed_png": b"\x89PNG-procesada"}
    return save_reviewed_receipt(repo, source_id="cifrado-1", image_bytes=b"\xff\xd8 foto original", original_filename="a.jpg",
                                 ocr_result=resultado, reviewed=ReviewedFields("2026-10-21", "TIENDA", 1000),
                                 receipt_format="A").receipt_id


def test_images_and_ocr_text_are_encrypted_on_disk_but_readable_through_the_repository(tmp_path: Path):
    repo = ReceiptRepository(tmp_path / "db.sqlite3", tmp_path / "images")
    receipt_id = _guardar(repo)
    registro = repo.get_receipt(receipt_id)
    en_disco = repo.resolve_image_path(registro["image_path"]).read_bytes()
    assert b"foto original" not in en_disco and crypto_service.is_encrypted_bytes(en_disco)
    assert repo.read_image(registro["image_path"]) == b"\xff\xd8 foto original"
    assert repo.read_image(registro["processed_image_path"]) == b"\x89PNG-procesada"
    # El texto OCR está cifrado en SQLite...
    import sqlite3
    crudo = sqlite3.connect(tmp_path / "db.sqlite3").execute("SELECT original_ocr_text FROM receipts").fetchone()[0]
    assert crudo.startswith(crypto_service.PREFIJO_TEXTO) and "TIENDA" not in crudo
    # ...y al leerlo vuelve descifrado, con el DNI ya enmascarado antes de cifrar.
    assert "TOTAL S/ 10.00" in registro["original_ocr_text"]
    assert "79360747" not in registro["original_ocr_text"] and "DNI ********" in registro["original_ocr_text"]


def test_listing_does_not_decrypt_or_expose_ocr_text(tmp_path: Path):
    repo = ReceiptRepository(tmp_path / "db.sqlite3", tmp_path / "images")
    _guardar(repo)
    assert "original_ocr_text" not in repo.list_receipts()[0]


def test_legacy_plaintext_records_remain_readable(tmp_path: Path):
    repo = ReceiptRepository(tmp_path / "db.sqlite3", tmp_path / "images")
    (tmp_path / "images" / "viejo_original.jpg").write_bytes(b"jpg en claro")
    repo.save_receipt({"receipt_date": "2026-01-01", "merchant": "Antigua", "total_cents": 100, "image_path": "viejo_original.jpg",
                       "original_ocr_text": "", "receipt_format": "A", "source_id": "viejo"})
    # Simula una fila anterior al cifrado: texto OCR en claro dentro de SQLite.
    import sqlite3
    with sqlite3.connect(tmp_path / "db.sqlite3") as con:
        con.execute("UPDATE receipts SET original_ocr_text = 'texto en claro'")
    registro = repo.list_receipts()[0]
    detalle = repo.get_receipt(registro["id"])
    assert detalle["original_ocr_text"] == "texto en claro"
    assert repo.read_image("viejo_original.jpg") == b"jpg en claro"


def test_lost_key_is_reported_without_crashing_the_record(tmp_path: Path, monkeypatch):
    repo = ReceiptRepository(tmp_path / "db.sqlite3", tmp_path / "images")
    receipt_id = _guardar(repo)
    monkeypatch.setenv(crypto_service.ENV_KEY, crypto_service.generate_key())  # clave distinta
    registro = repo.get_receipt(receipt_id)
    assert registro["original_ocr_text"] is None and "clave incorrecta" in registro["ocr_error"]
    with pytest.raises(DecryptionError):
        repo.read_image(registro["image_path"])
