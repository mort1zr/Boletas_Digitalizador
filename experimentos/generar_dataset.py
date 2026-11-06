"""Genera el conjunto de comprobantes SINTÉTICOS usado en el Avance 2.

Los comprobantes son ficticios (comercios, RUC, DNI y montos inventados) y se
declaran como tales en el informe. Sirven para medir el prototipo de forma
reproducible mientras se reúnen comprobantes reales anonimizados.

Formatos:
  A  Boleta de venta electrónica impresa (etiqueta "IMPORTE TOTAL").
  B  Ticket de caja de bodega/minimarket (etiqueta "TOTAL", efectivo y vuelto).
  C  Boleta de restaurante (etiqueta "TOTAL A PAGAR" y propina sugerida).

Condiciones de captura (simulan fotos con celular):
  ideal, inclinada, perspectiva, desenfoque, iluminacion, ruido

Uso:
  python experimentos/generar_dataset.py            # 8 por formato (24 en total)
  python experimentos/generar_dataset.py --por-formato 10 --semilla 7

Salida: experimentos/datos/imagenes/*.jpg y experimentos/datos/referencia.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos"
FUENTE_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FUENTE_MONO_NEGRITA = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
ANCHO_TICKET = 576  # 80 mm a 203 ppp, ancho típico de una impresora térmica
CONDICIONES = ["ideal", "inclinada", "perspectiva", "desenfoque", "iluminacion", "ruido"]

COMERCIOS = {
    "A": ["MINIMARKET SANTA ROSA S.A.C.", "FERRETERÍA EL PROGRESO E.I.R.L.", "BOTICA VIDA SANA S.A.C.",
          "LIBRERÍA SAN MARCOS S.R.L.", "COMERCIAL LOS ÁLAMOS S.A.C.", "DISTRIBUIDORA NORTEÑA E.I.R.L.",
          "ÓPTICA VISIÓN CLARA S.A.C.", "TEXTILES MIRAFLORES S.R.L.", "AGROVETERINARIA EL CAMPO SAC",
          "ELECTRO HOGAR PERÚ S.A.C."],
    "B": ["BODEGA DON PEPE", "MINIMARKET LA ECONOMÍA", "PANADERÍA EL TRIGAL", "BODEGA SAN JUAN",
          "AUTOSERVICIO LAS FLORES", "MARKET DOÑA ROSA", "BODEGA EL AHORRO", "FRUTERÍA LA CHACRA",
          "MINIMARKET EL VECINO", "BODEGA LOS ANDES"],
    "C": ["RESTAURANTE EL BUEN SABOR S.A.C.", "CEVICHERÍA PUERTO MAR E.I.R.L.", "POLLERÍA LA BRASA DORADA SAC",
          "CHIFA DRAGÓN DE ORO S.R.L.", "CAFETERÍA AROMA ANDINO S.A.C.", "PIZZERÍA LA TOSCANA E.I.R.L.",
          "SANGUCHERÍA EL PAISA SAC", "RESTAURANTE SABOR CRIOLLO S.A.C.", "JUGUERÍA FRUTAL S.R.L.",
          "PARRILLADAS EL GAUCHO SAC"],
}
PRODUCTOS = {
    "A": [("ARROZ EXTRA 5KG", "22.90"), ("ACEITE VEGETAL 1L", "9.80"), ("DETERGENTE 2KG", "18.50"),
          ("CUADERNO A4 100H", "6.50"), ("PARACETAMOL 500MG X10", "4.20"), ("FOCO LED 9W", "7.90"),
          ("CINTA AISLANTE", "3.50"), ("LECHE EVAPORADA X6", "21.60"), ("PAPEL HIGIENICO X4", "8.90")],
    "B": [("PAN FRANCES X10", "2.00"), ("LECHE GLORIA", "4.20"), ("HUEVOS 1KG", "8.50"), ("AZUCAR 1KG", "4.30"),
          ("GASEOSA 1.5L", "7.50"), ("FIDEOS 500G", "3.20"), ("ATUN EN LATA", "5.90"), ("GALLETAS", "1.50")],
    "C": [("CEVICHE CLASICO", "32.00"), ("LOMO SALTADO", "35.00"), ("1/4 POLLO A LA BRASA", "21.00"),
          ("ARROZ CHAUFA", "24.00"), ("CHICHA MORADA 1L", "12.00"), ("CAFE AMERICANO", "7.50"),
          ("PIZZA FAMILIAR", "45.00"), ("JUGO DE PAPAYA", "9.00"), ("INCA KOLA 500ML", "5.00")],
}


@dataclass
class Comprobante:
    identificador: str
    formato: str
    condicion: str
    fecha: date
    comercio: str
    total_centimos: int
    lineas: list[tuple[str, str, bool]]  # (texto, alineación, negrita)


def _dinero(valor: Decimal) -> str:
    return f"{valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _fila(izquierda: str, derecha: str, ancho: int = 40) -> str:
    espacio = max(1, ancho - len(izquierda) - len(derecha))
    return izquierda + " " * espacio + derecha


def _items(rng: random.Random, formato: str) -> tuple[list[str], Decimal]:
    elegidos = rng.sample(PRODUCTOS[formato], rng.randint(2, 4))
    lineas, total = [], Decimal("0")
    for nombre, precio in elegidos:
        cantidad = rng.randint(1, 3)
        importe = Decimal(precio) * cantidad
        total += importe
        lineas.append(_fila(f"{cantidad} {nombre}"[:30], _dinero(importe)))
    return lineas, total


def construir(rng: random.Random, formato: str, indice: int, condicion: str) -> Comprobante:
    comercio = COMERCIOS[formato][indice % len(COMERCIOS[formato])]
    fecha = date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))
    hora = f"{rng.randint(8, 21):02d}:{rng.randint(0, 59):02d}"
    items, total = _items(rng, formato)
    sep = "-" * 40
    lineas: list[tuple[str, str, bool]] = []
    if formato == "A":
        gravada = (total / Decimal("1.18"))
        igv = total - gravada.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        lineas += [(comercio, "c", True), (f"RUC 20{rng.randint(100000000, 999999999)}", "c", False),
                   ("AV. LOS INCAS 245 - LIMA", "c", False), ("BOLETA DE VENTA ELECTRONICA", "c", True),
                   (f"B001-{rng.randint(1000, 99999):08d}", "c", False), (sep, "c", False),
                   (f"Fecha de emision: {fecha:%d/%m/%Y}", "l", False), (f"Hora: {hora}", "l", False),
                   (f"Cliente: DNI {rng.randint(40000000, 79999999)}", "l", False), (sep, "c", False)]
        lineas += [(t, "l", False) for t in items]
        lineas += [(sep, "c", False), (_fila("OP. GRAVADA S/", _dinero(gravada)), "l", False),
                   (_fila("IGV 18% S/", _dinero(igv)), "l", False),
                   (_fila("IMPORTE TOTAL S/", _dinero(total)), "l", True), (sep, "c", False),
                   ("Representacion impresa de la", "c", False), ("Boleta de Venta Electronica", "c", False)]
    elif formato == "B":
        pago = (total / 10).to_integral_value(rounding="ROUND_CEILING") * 10
        lineas += [(comercio, "c", True), ("JR. HUANCAYO 1180", "c", False),
                   (f"TICKET N. {rng.randint(100, 9999):06d}", "c", False),
                   (f"{fecha:%d-%m-%y} {hora} CAJA 0{rng.randint(1, 4)}", "c", False), (sep, "c", False)]
        lineas += [(t, "l", False) for t in items]
        lineas += [(sep, "c", False), (_fila("SUBTOTAL", _dinero(total)), "l", False),
                   (_fila("TOTAL S/", _dinero(total)), "l", True),
                   (_fila("EFECTIVO S/", _dinero(pago)), "l", False),
                   (_fila("VUELTO S/", _dinero(pago - total)), "l", False), (sep, "c", False),
                   ("GRACIAS POR SU COMPRA", "c", False)]
    else:
        propina = (total * Decimal("0.10"))
        lineas += [(comercio, "c", True), (f"RUC 20{rng.randint(100000000, 999999999)}", "c", False),
                   ("CALLE LAS BEGONIAS 410", "c", False), ("BOLETA ELECTRONICA B002", "c", True),
                   (f"Fecha: {fecha:%Y-%m-%d} {hora}", "l", False),
                   (f"Mesa: {rng.randint(1, 20)}  Mozo: {rng.choice(['ANA', 'LUIS', 'CARLOS', 'ROSA'])}", "l", False),
                   (sep, "c", False)]
        lineas += [(t, "l", False) for t in items]
        lineas += [(sep, "c", False), (_fila("TOTAL A PAGAR S/", _dinero(total)), "l", True),
                   (_fila("Propina sugerida 10% S/", _dinero(propina)), "l", False), (sep, "c", False),
                   ("GRACIAS POR SU VISITA", "c", False)]
    cent = int((total * 100).to_integral_value())
    ident = f"{formato}{indice + 1:02d}_{condicion}"
    return Comprobante(ident, formato, condicion, fecha, comercio, cent, lineas)


def dibujar(comprobante: Comprobante) -> Image.Image:
    fuente = ImageFont.truetype(FUENTE_MONO, 22)
    negrita = ImageFont.truetype(FUENTE_MONO_NEGRITA, 22)
    alto_linea = 34
    alto = 60 + alto_linea * len(comprobante.lineas) + 60
    imagen = Image.new("L", (ANCHO_TICKET, alto), 250)
    lienzo = ImageDraw.Draw(imagen)
    y = 50
    for texto, alineacion, es_negrita in comprobante.lineas:
        f = negrita if es_negrita else fuente
        ancho_texto = lienzo.textlength(texto, font=f)
        x = (ANCHO_TICKET - ancho_texto) / 2 if alineacion == "c" else 24
        lienzo.text((x, y), texto, font=f, fill=25)
        y += alto_linea
    return imagen


def fotografiar(ticket: Image.Image, condicion: str, rng: random.Random) -> bytes:
    """Coloca el ticket sobre una mesa y aplica la condición de captura."""
    papel = np.array(ticket, dtype=np.float32)
    # Textura leve del papel térmico.
    papel += np.random.default_rng(rng.randint(0, 10**6)).normal(0, 3, papel.shape)
    alto_foto, ancho_foto = 1600, 1200
    escala = min(1400 / papel.shape[0], 900 / papel.shape[1])
    papel = cv2.resize(papel, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    h, w = papel.shape
    fondo = np.full((alto_foto, ancho_foto), 70, np.float32)
    fondo += np.random.default_rng(rng.randint(0, 10**6)).normal(0, 6, fondo.shape)
    fondo = cv2.GaussianBlur(fondo, (0, 0), 3)

    origen = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    cx, cy = ancho_foto / 2, alto_foto / 2
    destino = origen + np.float32([cx - w / 2, cy - h / 2])
    angulo = rng.uniform(-0.6, 0.6)
    if condicion == "inclinada":
        angulo = rng.choice([-1, 1]) * rng.uniform(4.0, 9.0)
    if condicion == "perspectiva":
        d = rng.uniform(0.07, 0.11) * w
        destino = destino + np.float32([[d, 0], [-d, 0], [d * 0.2, 0], [-d * 0.2, 0]])
        angulo = rng.uniform(-2, 2)
    rot = cv2.getRotationMatrix2D((cx, cy), angulo, 1.0)
    destino = cv2.transform(destino[None], rot)[0].astype(np.float32)
    matriz = cv2.getPerspectiveTransform(origen, destino)
    mascara = cv2.warpPerspective(np.ones_like(papel), matriz, (ancho_foto, alto_foto))
    deformado = cv2.warpPerspective(papel, matriz, (ancho_foto, alto_foto), flags=cv2.INTER_LINEAR)
    foto = fondo * (1 - mascara) + deformado * mascara

    if condicion == "desenfoque":
        foto = cv2.GaussianBlur(foto, (0, 0), rng.uniform(1.8, 2.4))
    if condicion == "iluminacion":
        yy, xx = np.mgrid[0:alto_foto, 0:ancho_foto].astype(np.float32)
        gradiente = 0.35 + 0.65 * (xx / ancho_foto * 0.6 + yy / alto_foto * 0.4)
        foto = foto * gradiente * 0.8
    calidad = 88
    if condicion == "ruido":
        foto = foto + np.random.default_rng(rng.randint(0, 10**6)).normal(0, 16, foto.shape)
        calidad = 35
    foto = np.clip(foto, 0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(foto).convert("RGB").save(buffer, format="JPEG", quality=calidad)
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--por-formato", type=int, default=8)
    parser.add_argument("--semilla", type=int, default=2026)
    args = parser.parse_args()
    rng = random.Random(args.semilla)
    carpeta = DATOS / "imagenes"
    carpeta.mkdir(parents=True, exist_ok=True)
    for viejo in carpeta.glob("*.jpg"):
        viejo.unlink()
    filas = []
    for desplazamiento, formato in enumerate("ABC"):
        for i in range(args.por_formato):
            # Rotación de condiciones: cada formato recorre las seis condiciones.
            condicion = CONDICIONES[(i + desplazamiento * 2) % len(CONDICIONES)]
            comp = construir(rng, formato, i, condicion)
            jpg = fotografiar(dibujar(comp), condicion, rng)
            nombre = f"{comp.identificador}.jpg"
            (carpeta / nombre).write_bytes(jpg)
            filas.append({
                "id": comp.identificador, "archivo": f"imagenes/{nombre}", "formato": formato,
                "condicion": condicion, "fecha": comp.fecha.isoformat(), "comercio": comp.comercio,
                "total": f"{comp.total_centimos / 100:.2f}",
                "texto_completo": " | ".join(t for t, _, _ in comp.lineas),
            })
    with (DATOS / "referencia.csv").open("w", newline="", encoding="utf-8") as fh:
        escritor = csv.DictWriter(fh, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)
    print(f"{len(filas)} comprobantes sintéticos en {carpeta}")


if __name__ == "__main__":
    main()
