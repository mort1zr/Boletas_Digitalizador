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
