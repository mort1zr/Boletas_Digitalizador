"""Reglas de negocio de revisión, guardado y exportación (sin dependencia de Streamlit).

Separar esta lógica de ``ui.py`` permite probar el flujo completo de guardado sin
levantar la interfaz.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from ocr_service import parse_amount
from privacy import mask_personal_data
from repository import ReceiptRepository

# Caracteres con los que una hoja de cálculo puede interpretar una celda como fórmula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class ReviewedFields:
    receipt_date: str
    merchant: str
    total_cents: int


@dataclass(frozen=True)
class SaveOutcome:
    receipt_id: int
    inserted: bool


def money_from_input(raw: str | None) -> tuple[int | None, str | None]:
    """Valida un total escrito por el operador y lo devuelve en céntimos.

    Usa el mismo analizador que el OCR para que ambos interpreten igual
    separadores de miles y decimales.
    """
    if raw is None or not str(raw).strip():
        return None, "Ingresa el total de la boleta."
    cents = parse_amount(str(raw))
    if cents is None:
        return None, "El total debe ser un número válido, por ejemplo 45.90."
    if cents <= 0:
        return None, "El total debe ser mayor que cero."
    return cents, None


def date_from_input(raw: str | None) -> tuple[str | None, str | None]:
    try:
        parsed = date.fromisoformat(str(raw or "").strip())
    except (ValueError, TypeError):
        return None, "La fecha debe ser válida y usar el formato AAAA-MM-DD."
    return parsed.isoformat(), None


def validate_review(date_value: str, merchant_value: str, total_value: str, confirmed: bool) -> tuple[ReviewedFields | None, list[str]]:
    errors: list[str] = []
    normal_date, date_error = date_from_input(date_value)
    if date_error:
        errors.append(date_error)
    normal_merchant = (merchant_value or "").strip()
    if not normal_merchant:
        errors.append("El nombre del comercio no puede estar vacío.")
    total_cents, total_error = money_from_input(total_value)
    if total_error:
        errors.append(total_error)
    if not confirmed:
        errors.append("Marca la confirmación explícita antes de guardar.")
    if errors:
        return None, errors
    assert normal_date is not None and total_cents is not None
    return ReviewedFields(normal_date, normal_merchant, total_cents), []


def save_reviewed_receipt(
    repository: ReceiptRepository,
    *,
    source_id: str,
    image_bytes: bytes,
    original_filename: str,
    ocr_result: Mapping[str, Any],
    reviewed: ReviewedFields,
    receipt_format: str,
) -> SaveOutcome:
    """Persiste imágenes y registro. Una acción ya guardada no se duplica ni se altera."""
    existing_id = repository.find_by_source_id(source_id)
    if existing_id is not None:
        # No se reescriben ni borran las imágenes: pertenecen al registro existente.
        return SaveOutcome(existing_id, False)

    fields = ocr_result.get("fields", {}) or {}
    original_extension = Path(original_filename or "").suffix.lower().lstrip(".") or "jpg"
    image_paths = repository.persist_images(source_id, image_bytes, ocr_result["processed_png"], original_extension)
    proposed_total, _ = money_from_input(fields.get("total", ""))
    record = {
        "receipt_date": reviewed.receipt_date,
        "merchant": reviewed.merchant,
        "total_cents": reviewed.total_cents,
        "image_path": image_paths[0],
        "processed_image_path": image_paths[1],
        # Minimización de datos: DNI, tarjetas y RUC de persona natural no se almacenan en claro.
        "original_ocr_text": mask_personal_data(ocr_result.get("raw_text", "")),
        "proposed_date": fields.get("receipt_date", ""),
        "proposed_merchant": fields.get("merchant", ""),
        "proposed_total_cents": proposed_total,
        "receipt_format": receipt_format,
        "source_id": source_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    try:
        receipt_id, inserted = repository.save_receipt(record)
    except Exception:
        # Solo se limpian las imágenes si ningún registro las referencia.
        if repository.find_by_source_id(source_id) is None:
            repository.remove_images(*image_paths)
        raise
    # Si otro guardado concurrente ganó la carrera, sus imágenes tienen los mismos
    # nombres (mismo source_id): no se eliminan.
    return SaveOutcome(receipt_id, inserted)


def format_total(cents: int | None) -> str:
    if cents is None:
        return "No detectado"
    return f"{(Decimal(int(cents)) / Decimal(100)):.2f}"


def csv_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["id", "fecha", "comercio", "total"])
    for row in rows:
        merchant = str(row["merchant"])
        # Evita que Excel/LibreOffice ejecuten el campo comercio como fórmula.
        if merchant.lstrip(" ").startswith(_FORMULA_PREFIXES):
            merchant = "'" + merchant
        writer.writerow([row["id"], row["receipt_date"], merchant, format_total(row["total_cents"])])
    return output.getvalue().encode("utf-8-sig")
