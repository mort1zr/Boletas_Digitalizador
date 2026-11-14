"""Preprocesamiento OpenCV, OCR con PaddleOCR y extracción heurística de campos.

Parámetros del pipeline documentados:
- Decodificación: cv2.IMREAD_COLOR.
- Redimensionado: lado máximo de 2400 px, INTER_AREA al reducir.
- Detección de inclinación: Canny (50, 150, apertureSize=3) y HoughLinesP
  (rho=1, theta=pi/180, threshold=50, minLineLength=max(30, 15% del ancho),
  maxLineGap=20); solo se aceptan líneas con |ángulo| <= 15 grados.
- Rotación: interpolación INTER_CUBIC y bordes blancos (255), ampliando el lienzo
  para evitar recortar los bordes de la boleta.
- Contraste (opcional, ``enhance=True``): CLAHE clipLimit=2.0 y tileGridSize=(8, 8).
- Reducción de ruido (opcional): bilateralFilter(d=5, sigmaColor=35, sigmaSpace=35).
- Recorte de la boleta (opcional, ``crop_document=True``): región clara más grande y perspectiva.
- PaddleOCR 3.x (CPU): detector PP-OCRv5_mobile_det y reconocedor latin_PP-OCRv5_mobile_rec
  (alfabeto latino: español con tildes y ñ), sin los módulos de orientación del documento, de
  desdistorsión ni de orientación de línea; oneDNN desactivado (falla en CPU con PaddlePaddle 3.3).
  Los pesos se descargan la primera vez (carpeta PADDLE_PDX_CACHE_HOME) o se toman de PADDLE_MODELOS.

Las reglas A/B son heurísticas iniciales. Los documentos de planificación no aportan
imágenes reales de boletas ni especifican su diseño visual; es necesario validarlas
con el conjunto de ajuste del equipo.
"""
from __future__ import annotations

import math
import os
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
    cropped: bool = False


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


def _order_corners(points: np.ndarray) -> np.ndarray:
    """Ordena 4 puntos como superior-izq., superior-der., inferior-der., inferior-izq."""
    by_sum, by_diff = points.sum(axis=1), np.diff(points, axis=1).ravel()
    return np.array([points[by_sum.argmin()], points[by_diff.argmin()], points[by_sum.argmax()], points[by_diff.argmax()]], dtype=np.float32)


def _crop_document(image: np.ndarray) -> np.ndarray | None:
    """Recorta y endereza el papel de la boleta cuando se distingue del fondo.

    Busca la región clara más grande (el papel sobre una mesa, madera o tela oscura), toma su
    rectángulo mínimo y corrige la perspectiva. Devuelve ``None`` si la foto ya es solo papel o
    si no hay un contraste claro con el fondo; entonces el pipeline sigue con la imagen completa.
    """
    height, width = image.shape[:2]
    scale = 800.0 / max(height, width)
    small = cv2.resize(image, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (7, 7), 0)
    threshold, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    close_size = max(5, int(min(small.shape[:2]) * 0.04))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (close_size, close_size)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    fraction = cv2.contourArea(contour) / float(small.shape[0] * small.shape[1])
    if not 0.12 <= fraction <= 0.92:
        return None
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, [contour], -1, 255, thickness=cv2.FILLED)
    inside, outside = gray[filled > 0], gray[filled == 0]
    if outside.size == 0 or float(inside.mean()) - float(outside.mean()) < 40.0:
        return None  # sin contraste claro: no se arriesga a recortar texto
    approx = cv2.approxPolyDP(cv2.convexHull(contour), 0.02 * cv2.arcLength(contour, True), True)
    corners = approx.reshape(-1, 2).astype(np.float32) if len(approx) == 4 else cv2.boxPoints(cv2.minAreaRect(contour))
    corners = _order_corners(np.asarray(corners, dtype=np.float32)) / scale
    top_left, top_right, bottom_right, bottom_left = corners
    out_width = int(round(max(np.linalg.norm(top_right - top_left), np.linalg.norm(bottom_right - bottom_left))))
    out_height = int(round(max(np.linalg.norm(bottom_left - top_left), np.linalg.norm(bottom_right - top_right))))
    if out_width < width * 0.15 or out_height < height * 0.15:
        return None
    # Margen del 1 % para no cortar el borde del texto.
    centre = corners.mean(axis=0)
    corners = (centre + (corners - centre) * 1.01).astype(np.float32)
    destination = np.array([[0, 0], [out_width - 1, 0], [out_width - 1, out_height - 1], [0, out_height - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(corners, destination)
    return cv2.warpPerspective(image, matrix, (out_width, out_height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def preprocess_image(image_bytes: bytes, crop_document: bool = False, enhance: bool = False) -> PreprocessedImage:
    """Decodifica, endereza y devuelve la imagen procesada para el OCR sin alterar el original.

    ``crop_document`` recorta el papel del fondo y corrige la perspectiva; ``enhance`` aplica CLAHE y
    filtro bilateral. Ambos están desactivados por defecto: en las 6 boletas reales del proyecto
    (experimentos/resultados/ronda3_preprocesado.md) la imagen en gris sin realce dio más campos
    correctos tanto con EasyOCR como con Tesseract (ronda 3), porque el realce amplifica el grano de la
    impresión térmica y el recorte no fue consistente. Se conservan como opciones hasta validarlos
    con una muestra mayor.
    """
    if not image_bytes:
        raise ValueError("El archivo de imagen está vacío.")
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    original = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if original is None or original.size == 0:
        raise ValueError("No se pudo decodificar la imagen. Prueba con otra foto (JPG, PNG o HEIC).")

    height, width = original.shape[:2]
    longest_side = max(height, width)
    if longest_side > 2400:
        scale = 2400.0 / longest_side
        original = cv2.resize(
            original,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )

    cropped = False
    if crop_document:
        document = _crop_document(original)
        if document is not None:
            original, cropped = document, True

    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    rotation = _estimate_skew(gray)
    if abs(rotation) >= 0.15:
        # En coordenadas de imagen (eje Y hacia abajo) un ángulo positivo de las
        # líneas es una inclinación horaria. getRotationMatrix2D gira en sentido
        # antihorario con ángulos positivos, así que rotar +rotation la endereza.
        gray = _rotate_expand(gray, rotation)

    if enhance:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        denoised = cv2.bilateralFilter(clahe.apply(gray), d=5, sigmaColor=35, sigmaSpace=35)
    else:
        denoised = gray
    ok, png_encoded = cv2.imencode(".png", denoised, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise RuntimeError("No se pudo codificar la imagen procesada.")
    return PreprocessedImage(image=denoised, png_bytes=png_encoded.tobytes(), rotation_degrees=rotation, cropped=cropped)


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


DETECTION_MODEL = "PP-OCRv5_mobile_det"
RECOGNITION_MODEL = "latin_PP-OCRv5_mobile_rec"


class PaddleReader:
    """Envoltorio de PaddleOCR que devuelve (caja, texto, confianza), el formato que usa ``_group_ocr_results``."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def read(self, image: np.ndarray) -> list[tuple[list[list[float]], str, float]]:
        # PaddleOCR espera una imagen de 3 canales; la copia procesada es de un solo canal.
        bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image
        items: list[tuple[list[list[float]], str, float]] = []
        for page in self._engine.predict(bgr):
            for polygon, text, score in zip(page["rec_polys"], page["rec_texts"], page["rec_scores"]):
                items.append((np.asarray(polygon, dtype=float).tolist(), str(text), float(score)))
        return items


@lru_cache(maxsize=1)
def _reader() -> PaddleReader:
    # Evita la comprobación de conectividad de PaddleX al arrancar (lenta o bloqueada sin Internet).
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise RuntimeError("PaddleOCR no está instalado. Ejecuta: pip install -r requirements.txt") from exc
    options: dict[str, Any] = {
        "text_detection_model_name": DETECTION_MODEL,
        "text_recognition_model_name": RECOGNITION_MODEL,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "enable_mkldnn": False,
    }
    local_models = os.environ.get("PADDLE_MODELOS", "").strip()
    if local_models:  # modelos ya descargados: DETECTION_MODEL_infer y RECOGNITION_MODEL_infer
        options["text_detection_model_dir"] = f"{local_models}/{DETECTION_MODEL}_infer"
        options["text_recognition_model_dir"] = f"{local_models}/{RECOGNITION_MODEL}_infer"
    # Los pesos preentrenados se descargan la primera vez que se ejecuta el OCR.
    return PaddleReader(PaddleOCR(**options))


def run_ocr(processed_image: np.ndarray) -> tuple[list[OCRLine], str]:
    reader = _reader()
    lines = _group_ocr_results(reader.read(processed_image))
    raw_text = "\n".join(line.text for line in lines)
    if not raw_text.strip():
        raise RuntimeError("El OCR no reconoció texto. Vuelve a intentar o carga una imagen más nítida.")
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


_DIGIT_LOOKALIKES = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1", "!": "1", "S": "5", "B": "8", "Z": "2"})
# Fecha con posibles letras en lugar de dígitos: "1O/II/06", "12/l1/26".
_DATE_LOOSE_RE = re.compile(r"(?<![0-9A-Za-z])([0-9OoQDIl|!SBZ]{1,2})\s*([./-])\s*([0-9OoQDIl|!SBZ]{1,2})\s*\2\s*([0-9OoQDIl|!SBZ]{2}(?:[0-9OoQDIl|!SBZ]{2})?)(?![0-9A-Za-z])")
# Año de 4 dígitos pegado a la hora: "12/11/202608:57".
_DATE_GLUED_TIME_RE = re.compile(r"((?<!\d)\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*(?:19|20)\d{2})(?=\d{2}\s*:\s*\d{2})")
_DATE_LABEL_RE = re.compile(r"(?i)\bfecha\b|\bemisi[oó]n\b")


def _repair_date_text(text: str) -> str:
    """Corrige errores típicos del OCR en una línea de fecha antes de buscar el patrón."""
    text = _DATE_GLUED_TIME_RE.sub(lambda m: m.group(1) + " ", text)
    # Las letras solo se tratan como dígitos si la línea está etiquetada como fecha o si, tras
    # corregirlas, queda una fecha de calendario válida: evita convertir palabras en fechas.
    def fix(match: re.Match[str]) -> str:
        parts = [match.group(1), match.group(3), match.group(4)]
        if not any(ch.isalpha() or ch in "|!" for part in parts for ch in part):
            return match.group(0)
        fixed = [part.translate(_DIGIT_LOOKALIKES) for part in parts]
        if not all(part.isdigit() for part in fixed):
            return match.group(0)
        candidate = re.match(_DATE_RE, f"{fixed[0]}/{fixed[1]}/{fixed[2]}")
        if candidate is None or _parse_date_match(candidate) is None:
            return match.group(0)
        return f"{fixed[0]}/{fixed[1]}/{fixed[2]}"

    return _DATE_LOOSE_RE.sub(fix, text)


def _extract_date(lines: Sequence[OCRLine]) -> str:
    lines = [OCRLine(_repair_date_text(line.text), line.confidence, line.y_center, line.x_left) for line in lines]
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


_LEGAL_FORM_RE = re.compile(r"\b(S\.?\s?A\.?\s?C\.?|S\.?\s?R\.?\s?L\.?|E\.?\s?I\.?\s?R\.?\s?L\.?|S\.?\s?A\.?)(?=\s|$|[^A-Za-z])", re.I)
_RUC_LABEL_RE = re.compile(r"\bR\.?U\.?C\b")
_ADDRESS_RE = re.compile(r"^(?:AV|AVDA|AVENIDA|JR|JIRON|CAL|CALLE|PSJE|PASAJE|PROLONGACION|URB|MZ|LT|GALERIA|CC|C\.C)\b[. ]")


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
        before_ruc = index + 1 < len(lines) and bool(_RUC_LABEL_RE.search(_normalise_text(lines[index + 1].text)))
        if _LEGAL_FORM_RE.search(text):
            score += 0.25
            # La razón social impresa justo antes del RUC es la mejor evidencia del comercio.
            if before_ruc or any(_RUC_LABEL_RE.search(_normalise_text(near.text)) for near in lines[index + 1:index + 4]):
                score += 2.0
        elif before_ruc:
            score += 1.5  # nombre de persona natural o nombre comercial impreso encima del RUC
        if _ADDRESS_RE.match(normal):
            score -= 1.5
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


# «DESCRIPCION  P.U.  TOTAL» es el encabezado de la tabla de ítems, no el total a pagar.
_COLUMN_HEADER_RE = re.compile(r"\bDESCRIPCION\b|\bP\.?\s?U\.?\b|\bPRECIO\b|\bCANT(?:IDAD)?\b|\bARTICULO\b|\bIMPORTE\s+TOTAL\s+IGV\b")
# Línea que es solo un importe: «S/ 175.20» (los vouchers de POS no siempre dicen «TOTAL»).
_ONLY_AMOUNT_RE = re.compile(r"^\W{0,3}(?:S|5|\$)\s*/?\.?\s*(\d{1,3}(?:[.,]\d{3})*[.,]\d{2}|\d+[.,]\d{2})\W{0,3}$", re.I)


_VOUCHER_MARKER_RE = re.compile(r"\b(?:VISA|MASTERCARD|MASTER|AMEX|DINERS|TARJETA|DEBITO|CREDITO|TERM|LOTE|REF|AP|VENTA\s*-?\s*ID|APROBADA|COPIA\s+(?:CLIENTE|PARA\s+EL\s+CLIENTE|DE\s+COMPRA))\b")


def _isolated_amount(lines: Sequence[OCRLine]) -> str:
    """Total de un voucher de POS sin etiqueta: el único importe que ocupa una línea completa.

    Solo se usa si el documento parece un voucher de tarjeta (al menos dos marcas como VISA, TERM,
    LOTE, REF o «COPIA CLIENTE»); en una boleta con ítems no se adivina el total sin etiqueta.
    """
    markers = {m.group(0) for line in lines for m in _VOUCHER_MARKER_RE.finditer(_normalise_text(line.text))}
    if len(markers) < 2:
        return ""
    found = {parse_amount(m.group(1)) for line in lines if (m := _ONLY_AMOUNT_RE.match(line.text.strip())) and line.confidence >= 0.35}
    found.discard(None)
    found = {amount for amount in found if amount and amount > 0}
    return _format_cents(found.pop()) if len(found) == 1 else ""


def _extract_total(lines: Sequence[OCRLine], receipt_format: str) -> str:
    scored: list[tuple[float, int, int]] = []  # puntaje, índice de línea, céntimos
    for index, line in enumerate(lines):
        normal = _normalise_text(line.text)
        label_score = _total_label_score(normal)
        if label_score < 0:
            continue
        amounts = _line_amounts(line.text)
        amount_index = index
        same_line = bool(amounts)
        if not amounts and index + 1 < len(lines) and not _COLUMN_HEADER_RE.search(normal):
            next_normal = _normalise_text(lines[index + 1].text)
            if not _is_excluded_amount_line(next_normal) and not _DATE_RE.search(lines[index + 1].text):
                amounts = _line_amounts(lines[index + 1].text)
                amount_index = index + 1
        positive_amounts = [amount for amount in amounts if amount > 0]
        if not positive_amounts:
            continue
        # Un total etiquetado normalmente tiene un solo importe; con varios, el final suele ser el total.
        amount = positive_amounts[-1]
        score = label_score + line.confidence + (1.5 if same_line else 0.0)
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


_UNIDADES = {
    "CERO": 0, "UN": 1, "UNO": 1, "UNA": 1, "DOS": 2, "TRES": 3, "CUATRO": 4, "CINCO": 5, "SEIS": 6, "SIETE": 7,
    "OCHO": 8, "NUEVE": 9, "DIEZ": 10, "ONCE": 11, "DOCE": 12, "TRECE": 13, "CATORCE": 14, "QUINCE": 15,
    "DIECISEIS": 16, "DIECISIETE": 17, "DIECIOCHO": 18, "DIECINUEVE": 19, "VEINTE": 20, "VEINTIUN": 21,
    "VEINTIUNO": 21, "VEINTIUNA": 21, "VEINTIDOS": 22, "VEINTITRES": 23, "VEINTICUATRO": 24, "VEINTICINCO": 25,
    "VEINTISEIS": 26, "VEINTISIETE": 27, "VEINTIOCHO": 28, "VEINTINUEVE": 29,
}
_DECENAS = {"TREINTA": 30, "CUARENTA": 40, "CINCUENTA": 50, "SESENTA": 60, "SETENTA": 70, "OCHENTA": 80, "NOVENTA": 90}
_CENTENAS = {
    "CIEN": 100, "CIENTO": 100, "DOSCIENTOS": 200, "TRESCIENTOS": 300, "CUATROCIENTOS": 400, "QUINIENTOS": 500,
    "SEISCIENTOS": 600, "SETECIENTOS": 700, "OCHOCIENTOS": 800, "NOVECIENTOS": 900,
}
# «SON: CUATRO Y 00/100 SOLES», «Son: Ciento veinte con 50/100 soles».
_SON_RE = re.compile(r"\bSON\b\s*:?\s*(?P<letras>[A-Z\s]+?)\s*(?:Y|CON)?\s*(?P<cent>\d{1,2})\s*/\s*100\b")


def _words_to_int(words: Sequence[str]) -> int | None:
    """Convierte palabras en español (hasta 999 999) a entero; ``None`` si alguna no se reconoce."""
    total, current, seen = 0, 0, False
    for word in words:
        if word == "Y":
            continue
        if word in _UNIDADES:
            current += _UNIDADES[word]
        elif word in _DECENAS:
            current += _DECENAS[word]
        elif word in _CENTENAS:
            current += _CENTENAS[word]
        elif word == "MIL":
            total += (current or 1) * 1000
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


def amount_in_words(text: str) -> int | None:
    """Importe en céntimos escrito en letras al pie de la boleta («SON: CUATRO Y 00/100 SOLES»)."""
    normal = _normalise_text(text)
    match = _SON_RE.search(normal)
    if not match:
        return None
    units = _words_to_int(match.group("letras").split())
    if units is None:
        return None
    return units * 100 + int(match.group("cent").ljust(2, "0")[:2])


def _crosscheck_total(lines: Sequence[OCRLine], total: str) -> tuple[str, str | None]:
    """Contrasta el total con el importe en letras. Devuelve (total, aviso o None).

    El importe en letras es independiente del número impreso: si ambos difieren, uno de los dos
    se leyó mal. Si el valor en letras aparece como importe en alguna otra línea, se adopta
    (lo respaldan dos lecturas); si no, se conserva el total y se avisa para revisarlo.
    """
    in_words = None
    for line in lines:
        in_words = amount_in_words(line.text)
        if in_words is not None:
            break
    if in_words is None:
        return total, None
    spoken = _format_cents(in_words)
    if total and parse_amount(total) == in_words:
        return total, None
    # Importes impresos en otras líneas (la propia línea «SON: …/100» no cuenta como respaldo).
    printed = {amount for line in lines if not _SON_RE.search(_normalise_text(line.text)) for amount in _line_amounts(line.text)}
    if not total:
        if in_words in printed:
            return spoken, "El total se tomó del importe en letras (\"SON: …\"), que coincide con un importe impreso; confírmalo."
        return "", f"El importe en letras indica S/ {spoken}, pero no se pudo leer el total numérico; verifícalo."
    if in_words in printed:
        return spoken, f"El total leído ({total}) no coincidía con el importe en letras; se corrigió a {spoken}. Verifícalo."
    return total, f"El total leído ({total}) no coincide con el importe en letras (S/ {spoken}); revisa cuál es correcto."


def _format_cents(cents: int) -> str:
    return f"{(Decimal(cents) / Decimal(100)):.2f}"


_SPLIT_DECIMAL_RE = re.compile(r"(?<=\d)\s*([.,])\s+(?=\d{2}(?!\d))|(?<=\d)\s+([.,])\s*(?=\d{2}(?!\d))")
_SPACE_BEFORE_DOT_RE = re.compile(r"(?<=[A-Za-zÁÉÍÓÚÑáéíóúñ])\s+\.(?=\s|$)")


def normalise_ocr_spacing(text: str) -> str:
    """Corrige espacios que el OCR inserta al unir cajas de texto vecinas.

    Los detectores por regiones (p. ej. los detectores de EasyOCR o PaddleOCR) pueden separar un importe
    en dos cajas ("65" y ".50"); al unirlas en una línea queda "65 .50" y el importe
    se lee mal. También aparece "S.A.C ." en razones sociales. La corrección es
    genérica y se aplica igual a cualquier motor OCR.
    """
    fixed = _SPLIT_DECIMAL_RE.sub(lambda m: m.group(1) or m.group(2), text)
    fixed = _SPACE_BEFORE_DOT_RE.sub(".", fixed)
    return re.sub(r"\s+", " ", fixed).strip()


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
    normalised_lines = [
        OCRLine(normalise_ocr_spacing(line.text), line.confidence, line.y_center, line.x_left)
        for line in normalised_lines
        if line.text.strip()
    ]
    receipt_format = receipt_format.strip().upper()
    if receipt_format not in ("A", "B"):
        raise ValueError("El formato debe ser A o B.")
    detected_date = _extract_date(normalised_lines)
    merchant = _extract_merchant(normalised_lines)
    total = _extract_total(normalised_lines, receipt_format)
    isolated_notice = None
    if not total and (total := _isolated_amount(normalised_lines)):
        isolated_notice = f"El total (S/ {total}) se tomó del único importe aislado de la boleta, sin etiqueta «TOTAL»; verifícalo."
    total, total_notice = _crosscheck_total(normalised_lines, total)
    warnings: list[str] = []
    if not detected_date:
        warnings.append("No se detectó una fecha suficientemente confiable; complétala o corrígela manualmente.")
    if not merchant:
        warnings.append("No se identificó con suficiente confianza el comercio; revisa el nombre manualmente.")
    if not total:
        warnings.append("No se identificó un total inequívoco; verifica que no sea subtotal, impuesto ni vuelto.")
    if isolated_notice and total and not total_notice:
        warnings.append(isolated_notice)
    if total_notice:
        warnings.append(total_notice)
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
        "cropped": processed.cropped,
        "processed_shape": list(processed.image.shape),
    }
