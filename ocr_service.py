"""Preprocesamiento OpenCV y extracción heurística de campos mediante EasyOCR.

Parámetros del pipeline documentados:
- Decodificación: cv2.IMREAD_COLOR.
- Redimensionado: lado máximo de 2400 px, INTER_AREA al reducir.
- Detección de inclinación: Canny (50, 150, apertureSize=3) y HoughLinesP
  (rho=1, theta=pi/180, threshold=50, minLineLength=max(30, 15% del ancho),
  maxLineGap=20); solo se aceptan líneas con |ángulo| <= 15 grados.
- Rotación: interpolación INTER_CUBIC y bordes blancos (255), ampliando el lienzo
  para evitar recortar los bordes de la boleta.
- Contraste: CLAHE clipLimit=2.0 y tileGridSize=(8, 8).
- Reducción de ruido: bilateralFilter(d=5, sigmaColor=35, sigmaSpace=35).
- EasyOCR: idiomas español e inglés, gpu=False; readtext con detail=1,
  paragraph=False, min_size=8, text_threshold=0.6, low_text=0.3,
  link_threshold=0.4, contrast_ths=0.1, adjust_contrast=0.7 y mag_ratio=1.5.

Las reglas A/B son heurísticas iniciales. Los documentos de planificación no aportan
imágenes reales de boletas ni especifican su diseño visual; es necesario validarlas
con el conjunto de ajuste del equipo.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Iterable, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float = 0.75
    y_center: float = 0.0
    x_left: float = 0.0


@dataclass(frozen=True)
class ReceiptFields:
    receipt_date: str = ""
    merchant: str = ""
    total: str = ""
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["warnings"] = list(self.warnings)
        return data


@dataclass(frozen=True)
class PreprocessedImage:
    image: np.ndarray
    png_bytes: bytes
    rotation_degrees: float


_DATE_RE = re.compile(r"(?<!\d)(\d{1,4})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})(?!\d)")
_AMOUNT_RE = re.compile(
    r"(?<!\d)(?:S\s*/\.?|PEN\b|USD\b|US\$|\$)?\s*"
    r"(-?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|-?\d+(?:[.,]\d{1,2})?)(?!\d)",
    re.IGNORECASE,
)
# Filas que nunca contienen el total final, aunque empiecen con estas palabras.
_EXCLUDED_AMOUNT_PREFIXES = (
    "SUBTOTAL", "SUB TOTAL", "IGV", "IVA", "IMPUESTO", "TAX", "VUELTO", "CAMBIO",
    "RECIBIDO", "PAGA CON", "EFECTIVO", "PROPINA", "DESCUENTO", "AHORRO",
    "GRAVADA", "INAFECTA", "EXONERADA", "BASE IMPONIBLE",
)
# Variantes etiquetadas como "TOTAL ..." que no son el importe a pagar.
_EXCLUDED_TOTAL_TERMS = (
    "TOTAL DESCUENTO", "TOTAL IMPUESTO", "TOTAL IGV", "TOTAL IVA",
)
# "TOTAL ITEMS 3" o "TOTAL ARTICULOS: 3" son cantidades, no importes.
_QUANTITY_TOTAL_RE = re.compile(
    r"\bTOTAL\s*(?:DE\s+)?(?:ITEMS?|ARTICULOS?|ARTS?|UNIDADES|UNDS?|CANTIDAD|CANT|PRODUCTOS?|PIEZAS?)\b"
    r"|\b(?:CANTIDAD|CANT|N(?:RO|UM|°)?\.?)\s*(?:TOTAL\s*)?(?:DE\s+)?(?:ITEMS?|ARTICULOS?|PRODUCTOS?)\b"
)
_DATE_EXCLUSION_LABELS = ("VENCIMIENTO", "VENCE EL", "CADUCIDAD", "VALIDO HASTA", "VÁLIDO HASTA", "DUE DATE")
_DATE_PREFERRED_LABELS = ("FECHA DE EMISION", "FECHA EMISION", "FECHA DE EMISIÓN", "FECHA", "EMISION", "EMISIÓN", "FECHA/HORA", "DATE")
_MERCHANT_EXCLUSIONS = (
    "BOLETA DE VENTA", "BOLETA ELECTRONICA", "BOLETA ELECTRÓNICA", "FACTURA ELECTRONICA",
    "FACTURA ELECTRÓNICA", "FACTURA", "COMPROBANTE DE PAGO", "TICKET DE VENTA", "TICKET ELECTRONICO",
    "TICKET", "BOLETA", "RECIBO", "RUC", "DNI", "DOCUMENTO", "ELECTRONICA", "ELECTRÓNICA", "FECHA", "CLIENTE",
    "CAJERO", "CAJA ", "DIRECCION", "DIRECCIÓN", "TELEFONO", "TELÉFONO", "CELULAR",
    "WWW.", "HTTP", "HTTPS", "EMAIL", "PAGINA", "PÁGINA", "MONEDA", "CODIGO", "CÓDIGO",
)


def _normalise_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_marks).strip().upper()


def _word_pattern(labels: Iterable[str]) -> re.Pattern[str]:
    """Une etiquetas normalizadas en un patrón con límites de palabra.

    Evita falsos positivos por subcadenas: "RUC" no debe descartar "TRUCK"
    ni "CRUCERO", y "TICKET" no debe descartar "TICKETERA SAC".
    """
    parts = []
    for label in dict.fromkeys(_normalise_text(label) for label in labels):
        escaped = re.escape(label.strip())
        # Las etiquetas que terminan en puntuación ("WWW.") no admiten \b al final.
        suffix = r"\b" if label.strip()[-1:].isalnum() else ""
        parts.append(rf"\b{escaped}{suffix}")
    return re.compile("|".join(parts))


_MERCHANT_EXCLUSION_RE = _word_pattern(_MERCHANT_EXCLUSIONS)
_DATE_EXCLUSION_NORMALISED = tuple(dict.fromkeys(_normalise_text(label) for label in _DATE_EXCLUSION_LABELS))
_DATE_PREFERRED_NORMALISED = tuple(dict.fromkeys(_normalise_text(label) for label in _DATE_PREFERRED_LABELS))


def _rotate_expand(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    cosine = abs(matrix[0, 0])
    sine = abs(matrix[0, 1])
    new_width = int(math.ceil((height * sine) + (width * cosine)))
    new_height = int(math.ceil((height * cosine) + (width * sine)))
    matrix[0, 2] += (new_width / 2.0) - center[0]
    matrix[1, 2] += (new_height / 2.0) - center[1]
    return cv2.warpAffine(
        image,
        matrix,
        (new_width, new_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )


def _estimate_skew(gray: np.ndarray) -> float:
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    width = gray.shape[1]
    min_line_length = max(30, int(width * 0.15))
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=50,
        minLineLength=min_line_length,
        maxLineGap=20,
    )
    angles: list[float] = []
    weights: list[float] = []
    if lines is not None:
        # OpenCV puede devolver HoughLinesP con forma (N, 1, 4) o (N, 4),
        # según la versión/build. Normalizar evita indexar una matriz 2D como si fuera 3D.
        for line in np.asarray(lines).reshape(-1, 4):
            x1, y1, x2, y2 = (int(v) for v in line)
            dx, dy = x2 - x1, y2 - y1
            if dx == 0:
                continue
            angle = math.degrees(math.atan2(dy, dx))
            if abs(angle) <= 15.0:
                angles.append(angle)
                weights.append(math.hypot(dx, dy))
    if not angles:
        return 0.0
    # Mediana ponderada por longitud: reduce la influencia de bordes pequeños o ruido.
    ordered = sorted(zip(angles, weights), key=lambda item: item[0])
    half_weight = sum(weights) / 2.0
    cumulative = 0.0
    for angle, weight in ordered:
        cumulative += weight
        if cumulative >= half_weight:
            return angle if abs(angle) >= 0.15 else 0.0
    return 0.0


def preprocess_image(image_bytes: bytes) -> PreprocessedImage:
    """Decodifica, corrige contraste/inclinación y devuelve PNG procesado sin alterar el original."""
    if not image_bytes:
        raise ValueError("El archivo de imagen está vacío.")
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    original = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if original is None or original.size == 0:
        raise ValueError("No se pudo decodificar la imagen. Prueba con otro JPG o PNG.")

    height, width = original.shape[:2]
    longest_side = max(height, width)
    if longest_side > 2400:
        scale = 2400.0 / longest_side
        original = cv2.resize(
            original,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )

    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    rotation = _estimate_skew(gray)
    if abs(rotation) >= 0.15:
        # En coordenadas de imagen (eje Y hacia abajo) un ángulo positivo de las
        # líneas es una inclinación horaria. getRotationMatrix2D gira en sentido
        # antihorario con ángulos positivos, así que rotar +rotation la endereza.
        gray = _rotate_expand(gray, rotation)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrast = clahe.apply(gray)
    denoised = cv2.bilateralFilter(contrast, d=5, sigmaColor=35, sigmaSpace=35)
    ok, png_encoded = cv2.imencode(".png", denoised, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise RuntimeError("No se pudo codificar la imagen procesada.")
    return PreprocessedImage(image=denoised, png_bytes=png_encoded.tobytes(), rotation_degrees=rotation)


@lru_cache(maxsize=1)
def _reader():
    try:
        import easyocr
    except ImportError as exc:
        raise RuntimeError("EasyOCR no está instalado. Ejecuta: pip install -r requirements.txt") from exc
    # Los pesos preentrenados se descargan la primera vez que se ejecuta el OCR.
    return easyocr.Reader(["es", "en"], gpu=False, verbose=False)


def _group_ocr_results(results: Sequence[Any]) -> list[OCRLine]:
    boxes: list[tuple[float, float, float, float, str, float]] = []
    heights: list[float] = []
    for item in results:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        box, text, confidence = item[0], str(item[1]).strip(), float(item[2])
        if not text:
            continue
        points = np.asarray(box, dtype=float).reshape(-1, 2)
        x_left = float(points[:, 0].min())
        y_top, y_bottom = float(points[:, 1].min()), float(points[:, 1].max())
        y_center = (y_top + y_bottom) / 2.0
        box_height = max(1.0, y_bottom - y_top)
        heights.append(box_height)
        boxes.append((y_center, x_left, box_height, confidence, text, y_top))
    if not boxes:
        return []

    threshold = max(8.0, float(np.median(heights)) * 0.65)
    boxes.sort(key=lambda item: (item[0], item[1]))
    grouped: list[list[tuple[float, float, float, float, str, float]]] = []
    for box in boxes:
        best_group = None
        best_distance = float("inf")
        for group in grouped:
            centre = sum(item[0] for item in group) / len(group)
            distance = abs(box[0] - centre)
            if distance <= threshold and distance < best_distance:
                best_group, best_distance = group, distance
        if best_group is None:
            grouped.append([box])
        else:
            best_group.append(box)
    lines: list[OCRLine] = []
    for group in grouped:
        group.sort(key=lambda item: item[1])
        text = " ".join(item[4] for item in group)
        confidence = sum(item[3] for item in group) / len(group)
        y_center = sum(item[0] for item in group) / len(group)
        x_left = min(item[1] for item in group)
        lines.append(OCRLine(text=text, confidence=confidence, y_center=y_center, x_left=x_left))
    return sorted(lines, key=lambda line: (line.y_center, line.x_left))


def run_ocr(processed_image: np.ndarray) -> tuple[list[OCRLine], str]:
    reader = _reader()
    results = reader.readtext(
        processed_image,
        detail=1,
        paragraph=False,
        min_size=8,
        text_threshold=0.6,
        low_text=0.3,
        link_threshold=0.4,
        contrast_ths=0.1,
        adjust_contrast=0.7,
        mag_ratio=1.5,
    )
    lines = _group_ocr_results(results)
    raw_text = "\n".join(line.text for line in lines)
    if not raw_text.strip():
        raise RuntimeError("EasyOCR no reconoció texto. Vuelve a intentar o carga una imagen más nítida.")
    return lines, raw_text


def _parse_date_match(match: re.Match[str]) -> str | None:
    first, second, third = match.group(1), match.group(2), match.group(3)
    try:
        if len(first) == 4:
            year, month, day = int(first), int(second), int(third)
        else:
            day, month, year = int(first), int(second), int(third)
            if year < 100:
                year += 2000 if year <= 69 else 1900
        return date(year, month, day).isoformat()
    except (ValueError, OverflowError):
        return None


def _extract_date(lines: Sequence[OCRLine]) -> str:
    candidates: dict[str, float] = {}
    normalised_exclusions = _DATE_EXCLUSION_NORMALISED
    normalised_preferred = _DATE_PREFERRED_NORMALISED
    for index, line in enumerate(lines):
        matches = list(_DATE_RE.finditer(line.text))
        previous_end = 0
        for match in matches:
            parsed = _parse_date_match(match)
            # Para comprobantes que ponen emisión y vencimiento en una misma línea,
            # evalúa la etiqueta situada antes de cada fecha, no toda la línea.
            label_context = line.text[previous_end:match.start()]
            normal_context = _normalise_text(label_context)
            excluded = any(label in normal_context for label in normalised_exclusions)
            previous_end = match.end()
            if not parsed or excluded or line.confidence < 0.35:
                continue
            score = line.confidence * 1.5 - min(index, 8) * 0.12
            if any(label in normal_context for label in normalised_preferred):
                score += 3.0
            candidates[parsed] = max(candidates.get(parsed, -999.0), score)
    if not candidates:
        return ""
    ranked = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < 0.8:
        return ""  # Hay más de una fecha sin evidencia suficiente para preferir una.
    return ranked[0][0]


def _extract_merchant(lines: Sequence[OCRLine]) -> str:
    candidates: list[tuple[float, int, str]] = []
    for index, line in enumerate(lines[:8]):
        text = re.sub(r"\s+", " ", line.text).strip(" -|:")
        normal = _normalise_text(text)
        if not text or line.confidence < 0.35 or _MERCHANT_EXCLUSION_RE.search(normal):
            continue
        if _DATE_RE.search(text) or (_AMOUNT_RE.search(text) and not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", text)):
            continue
        letters = sum(char.isalpha() for char in text)
        digits = sum(char.isdigit() for char in text)
        if letters < 3 or len(text) > 75 or digits > letters:
            continue
        # Se priorizan las líneas al inicio sin depender exclusivamente de mayúsculas.
        score = (max(0.0, 6.0 - index) * 0.65) + line.confidence * 1.8
        if re.search(r"\b(S\.?A\.?C\.?|S\.?R\.?L\.?|E\.?I\.?R\.?L\.?)\b", text, re.I):
            score += 0.25
        candidates.append((score, index, text))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_index, best_text = candidates[0]
    if best_score < 2.4:
        return ""
    # Dos líneas tempranas casi igual de plausibles no se resuelven a ciegas.
    if len(candidates) > 1:
        second_score, second_index, second_text = candidates[1]
        if second_index <= best_index + 1 and best_score - second_score < 0.18 and _normalise_text(second_text) != _normalise_text(best_text):
            return ""
    return best_text


def parse_amount(value: str) -> int | None:
    """Convierte un monto OCR a céntimos para evitar errores binarios de coma flotante."""
    token = value.strip().replace(" ", "").replace("S/", "").replace("s/", "")
    token = token.replace("PEN", "").replace("USD", "").replace("US$", "").replace("$", "")
    negative = token.startswith("-") or (token.startswith("(") and token.endswith(")"))
    token = token.strip("()")
    token = token.lstrip("-")
    if not token or not re.fullmatch(r"\d[\d.,]*", token):
        return None
    if "," in token and "." in token:
        decimal_sep = "," if token.rfind(",") > token.rfind(".") else "."
        grouping_sep = "." if decimal_sep == "," else ","
        token = token.replace(grouping_sep, "")
        token = token.replace(decimal_sep, ".")
    elif "," in token or "." in token:
        sep = "," if "," in token else "."
        pieces = token.split(sep)
        if len(pieces) == 2 and len(pieces[1]) in (1, 2):
            token = pieces[0] + "." + pieces[1].ljust(2, "0") if len(pieces[1]) == 1 else pieces[0] + "." + pieces[1]
        elif len(pieces) == 2 and len(pieces[1]) == 3:
            token = "".join(pieces)
        elif len(pieces) > 2:
            tail = pieces[-1]
            token = "".join(pieces[:-1]) + ("." + tail.ljust(2, "0") if len(tail) == 1 else ("." + tail if len(tail) == 2 else tail))
        else:
            token = "".join(pieces)
    try:
        amount = Decimal(token).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cents = int(amount * 100)
        return -cents if negative else cents
    except (InvalidOperation, ValueError):
        return None


def _line_amounts(text: str) -> list[int]:
    if _DATE_RE.search(text):
        return []
    amounts: list[int] = []
    for match in _AMOUNT_RE.finditer(text):
        parsed = parse_amount(match.group(1))
        if parsed is not None:
            amounts.append(parsed)
    return amounts


def _is_excluded_amount_line(normal: str) -> bool:
    # Se excluyen filas de subtotal/impuestos/vuelto, pero no un total final que
    # mencione que incluye IGV o IVA (por ejemplo, "TOTAL A PAGAR INCL. IGV").
    if any(term in normal for term in _EXCLUDED_TOTAL_TERMS):
        return True
    if any(re.match(rf"^\s*{re.escape(label)}\b", normal) for label in _EXCLUDED_AMOUNT_PREFIXES):
        return True
    if _QUANTITY_TOTAL_RE.search(normal):
        return True
    return bool(re.search(r"\bR\.?U\.?C\.?\b|\bDNI\b|NRO\.?\s*DOC", normal))


def _total_label_score(normal: str) -> float:
    if _is_excluded_amount_line(normal):
        return -1.0
    if any(term in normal for term in ("TOTAL A PAGAR", "IMPORTE TOTAL", "TOTAL PAGADO", "MONTO TOTAL", "NETO A PAGAR", "TOTAL FINAL")):
        return 10.0
    if "TOTAL GENERAL" in normal:
        return 9.0
    if re.search(r"\bTOTAL\b", normal):
        return 7.0
    return -1.0


def _extract_total(lines: Sequence[OCRLine], receipt_format: str) -> str:
    scored: list[tuple[float, int, int]] = []  # puntaje, índice de línea, céntimos
    for index, line in enumerate(lines):
        normal = _normalise_text(line.text)
        label_score = _total_label_score(normal)
        if label_score < 0:
            continue
        amounts = _line_amounts(line.text)
        amount_index = index
        if not amounts and index + 1 < len(lines):
            next_normal = _normalise_text(lines[index + 1].text)
            if not _is_excluded_amount_line(next_normal) and not _DATE_RE.search(lines[index + 1].text):
                amounts = _line_amounts(lines[index + 1].text)
                amount_index = index + 1
        positive_amounts = [amount for amount in amounts if amount > 0]
        if not positive_amounts:
            continue
        # Un total etiquetado normalmente tiene un solo importe; con varios, el final suele ser el total.
        amount = positive_amounts[-1]
        score = label_score + line.confidence
        if receipt_format.upper() == "B":
            score += min(index / max(1, len(lines)), 1.0) * 0.35
        scored.append((score, amount_index, amount))
    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) > 1:
            first, second = scored[0], scored[1]
            if first[2] != second[2] and first[0] - second[0] < 1.2:
                return ""
        return _format_cents(scored[0][2])

    # Formato A requiere una etiqueta identificable para reducir falsos positivos.
    # Formato B admite comprobantes tipo ticket: toma un importe monetario del tramo final.
    if receipt_format.upper() != "B" or not lines:
        return ""
    start_index = max(0, int(len(lines) * 0.60))
    fallback: list[tuple[int, float, int]] = []
    for index in range(start_index, len(lines)):
        line = lines[index]
        normal = _normalise_text(line.text)
        if _is_excluded_amount_line(normal) or _DATE_RE.search(line.text):
            continue
        # Evita tratar identificadores numéricos aislados como importes.
        has_currency = bool(re.search(r"S\s*/|PEN\b|USD\b|US\$|\$", line.text, re.I))
        has_decimal = bool(re.search(r"\d[.,]\d{1,2}(?!\d)", line.text))
        if not has_currency and not has_decimal:
            continue
        amounts = [value for value in _line_amounts(line.text) if value > 0]
        if amounts and line.confidence >= 0.35:
            fallback.append((index, line.confidence, amounts[-1]))
    if not fallback:
        return ""
    fallback.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return _format_cents(fallback[0][2])


def _format_cents(cents: int) -> str:
    return f"{(Decimal(cents) / Decimal(100)):.2f}"


def extract_fields(lines: Iterable[OCRLine | dict[str, Any] | str], receipt_format: str = "A") -> ReceiptFields:
    """Extrae fecha, comercio y total. Los campos no sustentados quedan vacíos."""
    normalised_lines: list[OCRLine] = []
    for item in lines:
        if isinstance(item, OCRLine):
            normalised_lines.append(item)
        elif isinstance(item, str):
            normalised_lines.append(OCRLine(item))
        elif isinstance(item, dict):
            normalised_lines.append(OCRLine(
                text=str(item.get("text", "")),
                confidence=float(item.get("confidence", 0.75)),
                y_center=float(item.get("y_center", 0.0)),
                x_left=float(item.get("x_left", 0.0)),
            ))
    normalised_lines = [line for line in normalised_lines if line.text.strip()]
    receipt_format = receipt_format.strip().upper()
    if receipt_format not in ("A", "B"):
        raise ValueError("El formato debe ser A o B.")
    detected_date = _extract_date(normalised_lines)
    merchant = _extract_merchant(normalised_lines)
    total = _extract_total(normalised_lines, receipt_format)
    warnings: list[str] = []
    if not detected_date:
        warnings.append("No se detectó una fecha suficientemente confiable; complétala o corrígela manualmente.")
    if not merchant:
        warnings.append("No se identificó con suficiente confianza el comercio; revisa el nombre manualmente.")
    if not total:
        warnings.append("No se identificó un total inequívoco; verifica que no sea subtotal, impuesto ni vuelto.")
    return ReceiptFields(detected_date, merchant, total, tuple(warnings))


def process_receipt(image_bytes: bytes, receipt_format: str = "A") -> dict[str, Any]:
    processed = preprocess_image(image_bytes)
    lines, raw_text = run_ocr(processed.image)
    fields = extract_fields(lines, receipt_format)
    return {
        "raw_text": raw_text,
        "lines": [asdict(line) for line in lines],
        "fields": fields.to_dict(),
        "processed_png": processed.png_bytes,
        "rotation_degrees": processed.rotation_degrees,
        "processed_shape": list(processed.image.shape),
    }
