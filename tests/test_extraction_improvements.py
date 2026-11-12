"""Mejoras de extracción: recorte de boleta, fecha con letras, comercio junto al RUC y total en letras."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

import ocr_service as o
from conftest import make_receipt_png


def _lineas(*textos):
    return [o.OCRLine(t) for t in textos]


# ------------------------------------------------------------------ importe en letras
@pytest.mark.parametrize("texto, esperado", [
    ("Son: CUATRO Y 00/100 SOL", 400),
    ("SON: CIENTO VEINTE CON 50/100 SOLES", 12050),
    ("Son: VEINTICUATRO Y 45/100 SOLES", 2445),
    ("SON: MIL DOSCIENTOS TREINTA Y CINCO Y 00/100 SOLES", 123500),
    ("SON: CIENTO SESENTA Y SEIS Y 20/100 SOLES", 16620),
    ("Son: Y 00/100 SOL 4.00", None),          # letras ilegibles: no se inventa un valor
    ("TOTAL A PAGAR 4.00", None),
])
def test_importe_en_letras(texto, esperado):
    assert o.amount_in_words(texto) == esperado


def test_total_contradictorio_se_corrige_si_otro_importe_lo_respalda():
    campos = o.extract_fields(_lineas("TIENDAS TAMBO S.A.C.", "RUC: 20563529378", "Fecha: 12/11/26",
                                      "TOTAL A PAGAR 7.00", "Efectivo 4.00", "Son: CUATRO Y 00/100 SOL"))
    assert campos.total == "4.00"
    assert any("importe en letras" in w for w in campos.warnings)


def test_total_contradictorio_sin_respaldo_se_conserva_y_avisa():
    campos = o.extract_fields(_lineas("TIENDA S.A.C.", "RUC: 20123456789", "TOTAL A PAGAR 7.00", "Son: CUATRO Y 00/100 SOL"))
    assert campos.total == "7.00"
    assert any("revisa cuál es correcto" in w for w in campos.warnings)


def test_total_coincidente_no_genera_aviso():
    campos = o.extract_fields(_lineas("TIENDA S.A.C.", "RUC: 20123456789", "Fecha: 12/11/26", "TOTAL A PAGAR 4.00", "Son: CUATRO Y 00/100 SOL"))
    assert campos.total == "4.00"
    assert not any("letras" in w for w in campos.warnings)


def test_total_ausente_se_recupera_del_importe_en_letras_si_esta_impreso():
    campos = o.extract_fields(_lineas("TIENDA S.A.C.", "Pagado 12.50", "Son: DOCE Y 50/100 SOLES"))
    assert campos.total == "12.50"


# ------------------------------------------------------------------ fechas
@pytest.mark.parametrize("texto, esperado", [
    ("Fecha: 1O/II/26", "2026-11-10"),
    ("Fecha: 12/l1/26", "2026-11-12"),
    ("Fecha: 12/11/2026 08:57", "2026-11-12"),
    ("Fecha: 12/11/202608:57", "2026-11-12"),       # fecha pegada a la hora
    ("Emision: 05-11-2026", "2026-11-05"),
])
def test_fecha_tolera_errores_de_ocr(texto, esperado):
    assert o.extract_fields(_lineas("TIENDA S.A.C.", texto, "TOTAL 1.00")).receipt_date == esperado


def test_palabras_no_se_convierten_en_fecha():
    assert o.extract_fields(_lineas("TIENDA S.A.C.", "SOLO/DOS/BIEN", "TOTAL 1.00")).receipt_date == ""


def test_fecha_imposible_con_letras_se_descarta():
    assert o.extract_fields(_lineas("TIENDA S.A.C.", "Fecha: OO/OO/26", "TOTAL 1.00")).receipt_date == ""


# ------------------------------------------------------------------ comercio junto al RUC
def test_comercio_es_la_razon_social_justo_antes_del_ruc():
    campos = o.extract_fields(_lineas("TAMBO +", "TIENDAS TAMBO S.A.C.", "AV. JAVIER PRADO ESTE NRO. 6210 INT. 1201", "AV AREQUIPA 1900 - LINCE",
                                      "RUC: 20563529378", "BOLETA DE VENTA ELECTRONICA", "Fecha: 12/11/26", "TOTAL A PAGAR 4.00"))
    assert campos.merchant == "TIENDAS TAMBO S.A.C."


# ------------------------------------------------------------------ recorte de la boleta
def _boleta_sobre_mesa(angulo=8.0):
    papel = cv2.imdecode(np.frombuffer(make_receipt_png(["TIENDA S.A.C.", "TOTAL S/ 45.90"], size=(500, 900)), np.uint8), cv2.IMREAD_COLOR)
    fondo = np.full((1400, 1000, 3), 45, np.uint8)
    x, y = 250, 200
    fondo[y:y + 900, x:x + 500] = papel
    matriz = cv2.getRotationMatrix2D((500, 650), angulo, 1.0)
    return cv2.warpAffine(fondo, matriz, (1000, 1400), borderValue=(45, 45, 45))


def test_recorta_la_boleta_del_fondo_oscuro():
    ok, codificada = cv2.imencode(".jpg", _boleta_sobre_mesa())
    resultado = o.preprocess_image(codificada.tobytes(), crop_document=True)
    assert resultado.cropped
    alto, ancho = resultado.image.shape[:2]
    assert alto > ancho and ancho < 700           # quedó solo el papel, vertical
    assert abs(resultado.rotation_degrees) < 1.0   # y ya enderezado


def test_recorte_esta_desactivado_por_defecto():
    ok, codificada = cv2.imencode(".jpg", _boleta_sobre_mesa())
    assert not o.preprocess_image(codificada.tobytes()).cropped


def test_imagen_solo_de_papel_no_se_recorta():
    assert not o.preprocess_image(make_receipt_png(["TIENDA S.A.C.", "TOTAL S/ 45.90"]), crop_document=True).cropped


def test_imagen_uniforme_no_se_recorta():
    ok, codificada = cv2.imencode(".png", np.full((800, 600, 3), 200, np.uint8))
    assert not o.preprocess_image(codificada.tobytes(), crop_document=True).cropped


def test_realce_es_opcional_y_cambia_la_imagen():
    imagen = make_receipt_png(["TIENDA S.A.C.", "TOTAL S/ 45.90"])
    sin = o.preprocess_image(imagen).image
    con = o.preprocess_image(imagen, enhance=True).image
    assert sin.shape == con.shape and not np.array_equal(sin, con)
