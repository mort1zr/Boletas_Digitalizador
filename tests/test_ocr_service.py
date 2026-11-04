from ocr_service import OCRLine, extract_fields, parse_amount


def test_parse_amount_peruvian_and_us_formats():
    assert parse_amount("S/ 1,234.56") == 123456
    assert parse_amount("1.234,56") == 123456
    assert parse_amount("12,5") == 1250
    assert parse_amount("23.90") == 2390


def test_format_a_extracts_labelled_total_not_subtotal_tax_or_change():
    lines = [
        OCRLine("SUPERMERCADO EJEMPLO S.A.C.", 0.99),
        OCRLine("BOLETA ELECTRONICA", 0.95),
        OCRLine("Fecha de emisión: 21/10/2026", 0.95),
        OCRLine("Subtotal S/ 100.00", 0.99),
        OCRLine("IGV S/ 18.00", 0.99),
        OCRLine("TOTAL A PAGAR S/ 118.00", 0.99),
        OCRLine("Vuelto S/ 2.00", 0.99),
    ]
    result = extract_fields(lines, "A")
    assert result.receipt_date == "2026-10-21"
    assert result.merchant == "SUPERMERCADO EJEMPLO S.A.C."
    assert result.total == "118.00"


def test_format_b_can_use_last_currency_amount_if_total_label_is_missing():
    lines = [
        OCRLine("TIENDA DEMO", 0.95),
        OCRLine("Fecha 20/10/2026", 0.95),
        OCRLine("Pan 3.50", 0.90),
        OCRLine("Leche 5.20", 0.90),
        OCRLine("S/ 8.70", 0.90),
    ]
    result = extract_fields(lines, "B")
    assert result.receipt_date == "2026-10-20"
    assert result.total == "8.70"


def test_ambiguous_unlabelled_dates_are_left_blank():
    lines = [
        OCRLine("COMERCIO DEMO", 0.9),
        OCRLine("21/10/2026", 0.9),
        OCRLine("22/10/2026", 0.9),
        OCRLine("TOTAL S/ 10.00", 0.9),
    ]
    result = extract_fields(lines, "A")
    assert result.receipt_date == ""
    assert result.total == "10.00"


def test_total_that_mentions_included_tax_is_not_excluded():
    result = extract_fields([
        OCRLine("TIENDA EJEMPLO", 0.9),
        OCRLine("Fecha 23/10/2026", 0.9),
        OCRLine("TOTAL A PAGAR INCL. IGV S/ 59.00", 0.9),
    ], "A")
    assert result.total == "59.00"


def test_preprocessing_returns_a_separate_valid_png():
    import cv2
    import numpy as np
    from ocr_service import preprocess_image

    canvas = np.full((520, 360, 3), 255, dtype=np.uint8)
    cv2.putText(canvas, "BOLETA DEMO", (25, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    cv2.putText(canvas, "TOTAL S/ 15.50", (25, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    ok, encoded = cv2.imencode(".png", canvas)
    assert ok
    original_bytes = encoded.tobytes()

    result = preprocess_image(original_bytes)
    decoded = cv2.imdecode(np.frombuffer(result.png_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert decoded is not None
    assert decoded.size > 0
    assert result.image.ndim == 2
    assert result.rotation_degrees == result.rotation_degrees  # no NaN
    assert original_bytes == encoded.tobytes()  # los bytes originales no se sobrescriben


def test_emission_date_can_be_extracted_when_due_date_is_on_same_line():
    result = extract_fields([
        OCRLine("TIENDA DEMO", 0.9),
        OCRLine("Fecha de emisión 20/10/2026 Vencimiento 30/10/2026", 0.95),
        OCRLine("TOTAL S/ 15.00", 0.9),
    ], "A")
    assert result.receipt_date == "2026-10-20"


# ---------------------------------------------------------------------------
# Corrección de inclinación
# ---------------------------------------------------------------------------
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from conftest import ruled_image_png  # noqa: E402
from ocr_service import (  # noqa: E402
    _estimate_skew,
    _extract_merchant,
    _group_ocr_results,
    preprocess_image,
    process_receipt,
    run_ocr,
)


@pytest.mark.parametrize("tilt", [-8.0, -4.0, 3.0, 6.0, 10.0])
def test_preprocessing_straightens_tilted_image(tilt):
    result = preprocess_image(ruled_image_png(tilt))
    # La inclinación detectada tiene el signo de la inclinación de las líneas...
    assert result.rotation_degrees == pytest.approx(-tilt, abs=0.6)
    # ...y tras corregirla la imagen queda prácticamente horizontal (no duplicada).
    assert abs(_estimate_skew(result.image)) < 0.6


def test_straight_image_is_not_rotated():
    result = preprocess_image(ruled_image_png(0.0))
    assert result.rotation_degrees == 0.0


def test_large_images_are_downscaled_to_2400px():
    canvas = np.full((3000, 1200, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", canvas)
    result = preprocess_image(encoded.tobytes())
    assert max(result.image.shape[:2]) == 2400


@pytest.mark.parametrize("payload", [b"", b"no es una imagen"])
def test_invalid_images_are_rejected(payload):
    with pytest.raises(ValueError):
        preprocess_image(payload)


# ---------------------------------------------------------------------------
# Montos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("118.00", 11800),
        ("118,00", 11800),
        ("S/ 45.9", 4590),
        ("S/45,90", 4590),
        ("1.234,56", 123456),
        ("1,234.56", 123456),
        ("1.234", 123400),
        ("1,234", 123400),
        ("1.234.567,8", 123456780),
        ("USD 10", 1000),
        ("$ 7.5", 750),
        ("-5.00", -500),
        ("(5.00)", -500),
        ("", None),
        ("abc", None),
        ("12a", None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


# ---------------------------------------------------------------------------
# Total
# ---------------------------------------------------------------------------
def test_total_items_count_is_not_taken_as_amount():
    result = extract_fields([
        OCRLine("TIENDA DEMO", 0.9),
        OCRLine("TOTAL ITEMS 3", 0.95),
        OCRLine("TOTAL ARTICULOS: 3", 0.95),
    ], "A")
    assert result.total == ""


def test_total_items_does_not_compete_with_real_total():
    result = extract_fields([
        OCRLine("TIENDA DEMO", 0.9),
        OCRLine("CANT. DE ITEMS 2", 0.95),
        OCRLine("TOTAL S/ 25.40", 0.95),
    ], "A")
    assert result.total == "25.40"


def test_total_label_with_item_count_in_parentheses_is_kept():
    result = extract_fields([OCRLine("TIENDA DEMO", 0.9), OCRLine("TOTAL A PAGAR (3 ITEMS) S/ 50.00", 0.95)], "A")
    assert result.total == "50.00"


def test_total_amount_on_next_line_is_used():
    result = extract_fields([OCRLine("TIENDA DEMO", 0.9), OCRLine("IMPORTE TOTAL", 0.95), OCRLine("S/ 33.30", 0.95)], "A")
    assert result.total == "33.30"


def test_format_a_without_label_leaves_total_empty():
    result = extract_fields([OCRLine("TIENDA DEMO", 0.9), OCRLine("Pan 3.50", 0.9), OCRLine("S/ 8.70", 0.9)], "A")
    assert result.total == ""
    assert any("total" in warning.lower() for warning in result.warnings)


def test_conflicting_total_labels_are_left_blank():
    result = extract_fields([OCRLine("TIENDA DEMO", 0.9), OCRLine("TOTAL S/ 10.00", 0.9), OCRLine("TOTAL S/ 12.00", 0.9)], "A")
    assert result.total == ""


def test_format_b_fallback_ignores_change_and_tax_lines():
    result = extract_fields([
        OCRLine("TIENDA DEMO", 0.9),
        OCRLine("Pan 3.50", 0.9),
        OCRLine("Leche 5.20", 0.9),
        OCRLine("Gracias por su compra", 0.9),
        OCRLine("S/ 8.70", 0.9),  # el respaldo solo mira el 40 % final del ticket
        OCRLine("IGV 1.33", 0.9),
        OCRLine("VUELTO 1.30", 0.9),
    ], "B")
    assert result.total == "8.70"


# ---------------------------------------------------------------------------
# Comercio
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["TRUCK STOP SAC", "CRUCERO DEL SUR", "TICKETERA LIMA SRL", "CAJAMARCA MARKET"])
def test_merchant_exclusions_use_word_boundaries(name):
    assert _extract_merchant([OCRLine(name, 0.95), OCRLine("Fecha 20/10/2026", 0.9)]) == name


@pytest.mark.parametrize("label", ["RUC 20123456789", "BOLETA DE VENTA ELECTRONICA", "https://tienda.pe", "Cajero: Ana"])
def test_merchant_labels_are_still_excluded(label):
    assert _extract_merchant([OCRLine(label, 0.95)]) == ""


def test_merchant_skips_document_headers():
    lines = [OCRLine("BOLETA ELECTRONICA", 0.95), OCRLine("RUC 20123456789", 0.95), OCRLine("Bodega San Juan", 0.9)]
    assert _extract_merchant(lines) == "Bodega San Juan"


def test_low_confidence_lines_are_not_used_for_merchant():
    assert _extract_merchant([OCRLine("TIENDA DUDOSA", 0.2)]) == ""


# ---------------------------------------------------------------------------
# Fecha
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fecha: 05/03/2026", "2026-03-05"),
        ("Fecha: 05-03-26", "2026-03-05"),
        ("Fecha: 05.03.2026", "2026-03-05"),
        ("Fecha: 2026-03-05", "2026-03-05"),
        ("Fecha: 31/02/2026", ""),
    ],
)
def test_date_formats(text, expected):
    assert extract_fields([OCRLine("TIENDA", 0.9), OCRLine(text, 0.9)], "A").receipt_date == expected


def test_due_date_alone_is_ignored():
    assert extract_fields([OCRLine("TIENDA", 0.9), OCRLine("Vencimiento 30/10/2026", 0.9)], "A").receipt_date == ""


# ---------------------------------------------------------------------------
# Entradas y agrupación OCR
# ---------------------------------------------------------------------------
def test_extract_fields_accepts_strings_and_dicts_and_validates_format():
    result = extract_fields(["TIENDA DEMO", {"text": "TOTAL S/ 9.90", "confidence": 0.9}], "a")
    assert result.total == "9.90"
    with pytest.raises(ValueError):
        extract_fields(["TIENDA"], "C")


def _box(x, y, w=80, h=20):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def test_ocr_boxes_on_same_row_are_joined_left_to_right():
    results = [
        (_box(300, 100), "S/ 20.00", 0.9),
        (_box(20, 102), "TOTAL", 0.8),
        (_box(20, 20), "TIENDA", 0.95),
        (_box(20, 60), "", 0.9),
        ("basura",),
    ]
    lines = _group_ocr_results(results)
    assert [line.text for line in lines] == ["TIENDA", "TOTAL S/ 20.00"]
    assert lines[1].confidence == pytest.approx(0.85)


class _FakeReader:
    def __init__(self, results):
        self.results = results
        self.calls = 0

    def readtext(self, image, **kwargs):
        self.calls += 1
        assert image.ndim == 2  # recibe la copia procesada en escala de grises
        return self.results


def test_process_receipt_end_to_end_with_stubbed_ocr(monkeypatch):
    import ocr_service
    from conftest import make_receipt_png

    reader = _FakeReader([
        (_box(20, 20), "MINIMARKET LOS ANDES", 0.95),
        (_box(20, 60), "Fecha de emision: 21/10/2026", 0.93),
        (_box(20, 100), "SUBTOTAL", 0.9), (_box(300, 100), "S/ 100.00", 0.9),
        (_box(20, 140), "IGV", 0.9), (_box(300, 140), "S/ 18.00", 0.9),
        (_box(20, 180), "TOTAL A PAGAR", 0.92), (_box(300, 180), "S/ 118.00", 0.94),
    ])
    monkeypatch.setattr(ocr_service, "_reader", lambda: reader)
    image = make_receipt_png(["MINIMARKET LOS ANDES", "TOTAL A PAGAR S/ 118.00"], tilt_degrees=5)
    result = process_receipt(image, "A")
    assert reader.calls == 1
    assert result["fields"]["receipt_date"] == "2026-10-21"
    assert result["fields"]["merchant"] == "MINIMARKET LOS ANDES"
    assert result["fields"]["total"] == "118.00"
    assert result["fields"]["warnings"] == []
    assert "TOTAL A PAGAR S/ 118.00" in result["raw_text"]
    assert result["processed_png"].startswith(b"\x89PNG")
    assert result["rotation_degrees"] == pytest.approx(-5, abs=1.0)


def test_run_ocr_fails_clearly_when_no_text(monkeypatch):
    import ocr_service

    monkeypatch.setattr(ocr_service, "_reader", lambda: _FakeReader([]))
    with pytest.raises(RuntimeError, match="no reconoció texto"):
        run_ocr(np.full((50, 50), 255, dtype=np.uint8))
