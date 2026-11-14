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


# ------------------------------------------------------------------ total sin etiqueta y encabezados de columna
def test_total_ignora_el_encabezado_de_columna_con_total():
    campos = o.extract_fields(_lineas("DESCRIPCION P.U. TOTAL", "[2.00]PANT SEDA 43.00 86.00", "[1.00]PANTALON 43.00 43.00",
                                      "GRAVADO: S/ 109.32", "IGV: S/ 19.68", "TOTAL: S/ 129.00"))
    assert campos.total == "129.00"


def test_voucher_sin_etiqueta_usa_el_unico_importe_aislado_y_avisa():
    campos = o.extract_fields(_lineas("NIUBIZ", "VISA BANCO SCOTIABANK", "03/09/26 12:25", "TERM: 10005039 LOTE: 008", "S/ 175.20", "COPIA CLIENTE"))
    assert campos.total == "175.20"
    assert any("único importe aislado" in w for w in campos.warnings)


def test_importe_aislado_ambiguo_no_se_adivina():
    campos = o.extract_fields(_lineas("TIENDA", "S/ 10.00", "S/ 20.00"))
    assert campos.total == ""


def test_importe_aislado_con_ocr_5_barra_en_lugar_de_s_barra():
    assert o.extract_fields(_lineas("NIUBIZ", "VISA BANCO", "TERM: 10005039 LOTE: 008", "5/ 175.20")).total == "175.20"


def test_total_etiquetado_tiene_prioridad_sobre_el_importe_aislado():
    campos = o.extract_fields(_lineas("OPENPAY", "S/ 12.00", "TOTAL S/50.00"))
    assert campos.total == "50.00"


# ------------------------------------------------------------------ comercio: persona natural y direcciones
def test_comercio_persona_natural_justo_antes_del_ruc():
    campos = o.extract_fields(_lineas("TOSCANO HUILLCA PAUL CHRISTIAN", "RUC 10480354465", "PROLONGACION GAMARRA # 860 (TDA. 138-139)",
                                      "GALERIA AZUL GAMARRA LA VICTORIA- LIMA", "BOLETA DE VENTA ELECTRONICA"))
    assert campos.merchant == "TOSCANO HUILLCA PAUL CHRISTIAN"


def test_una_direccion_no_gana_al_nombre_del_comercio():
    campos = o.extract_fields(_lineas("PROLONGACION GAMARRA 860 TDA 138", "TIENDA LA ESTRELLA", "BOLETA DE VENTA ELECTRONICA"))
    assert campos.merchant == "TIENDA LA ESTRELLA"


def test_boleta_con_items_sin_etiqueta_no_adivina_el_total():
    campos = o.extract_fields(_lineas("TIENDA DEMO", "Pan 3.50", "S/ 8.70"))
    assert campos.total == ""


# ------------------------------------------------------------------ fechas implausibles e importe en letras sin «SON»
def test_un_importe_negativo_no_se_toma_como_fecha():
    campos = o.extract_fields(_lineas("TIENDA S.A.C.", "SAPOLIO COCO X900 -2.10 3.50", "Saldo al 07/11/26: 317 pts", "TOTAL 10.00"))
    assert campos.receipt_date == "2026-11-07"


@pytest.mark.parametrize("texto", ["Fecha: 25/08/2605", "Fecha: 05/11/2613", "Fecha: 01/02/2010"])
def test_fechas_con_anio_implausible_se_descartan(texto):
    assert o.extract_fields(_lineas("TIENDA S.A.C.", texto, "TOTAL 1.00")).receipt_date == ""


def test_importe_en_letras_sin_la_palabra_son():
    assert o.amount_in_words("VEINTISEIS Y 68/100 SOLES") == 2668
    assert o.amount_in_words("SIETE Y 80/100 S0LES") == 780
    assert o.amount_in_words("TARJ BANC 7.80") is None


def test_total_ambiguo_se_resuelve_con_el_importe_en_letras_sin_son():
    campos = o.extract_fields(_lineas("COMPANIA HARD DISCOUNT S.A.C.", "RUC 20608280333", "IMPORTE TOTAL S/ S/ 7.80 1.19",
                                      "TOTAL A PAGAR S/ 7.80", "SIETE Y 80/100 S0LES", "TARJ BANC 7.80"))
    assert campos.total == "7.80"
