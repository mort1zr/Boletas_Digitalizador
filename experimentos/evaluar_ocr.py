"""Experimentos 1 y 3 del Avance 2: exactitud de extracción y comparación de motores OCR.

Ejecuta el pipeline real del prototipo (preprocesamiento OpenCV + OCR + reglas de
extracción de ``ocr_service``) sobre cada comprobante de ``datos/referencia.csv``
y compara fecha, comercio y total con los valores de referencia.

Para comparar motores de forma justa, EasyOCR y Tesseract reciben la MISMA imagen
preprocesada y sus líneas pasan por las MISMAS reglas de extracción; solo cambia
el motor de reconocimiento.

Los comprobantes son fotografías REALES y anonimizadas (datos/imagenes/). El campo
«comercio» de referencia admite varias formas válidas separadas por «|» (razón social
o nombre comercial impresos en el encabezado).

Uso:
  python experimentos/evaluar_ocr.py --motor ambos                 # ronda 2 (prototipo actual)
  python experimentos/evaluar_ocr.py --motor ambos --sin-normalizacion \
         --salida experimentos/resultados/ronda1_sin_normalizacion    # ronda 1
  python experimentos/evaluar_ocr.py --calibrar-tesseract          # elige el modo psm

Salida: un CSV por motor con el detalle por comprobante, y resumen.json / resumen.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import re
import statistics
import sys
import time
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

RAIZ_EXPERIMENTOS = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ_EXPERIMENTOS.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import ocr_service  # noqa: E402
from ocr_service import OCRLine, extract_fields, preprocess_image  # noqa: E402

DATOS = RAIZ_EXPERIMENTOS / "datos"
RESULTADOS = RAIZ_EXPERIMENTOS / "resultados"
TESSERACT_PSM = 6  # se fija con --calibrar-tesseract (el modo con mayor exactitud global)
TESSERACT_CONFIG = f"--oem 1 --psm {TESSERACT_PSM}"


def normalizar(texto: str) -> str:
    """Mayúsculas, sin tildes y sin espacios repetidos (comparación de comercio)."""
    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(sin_tildes.upper().split())


# --------------------------------------------------------------------------- motores
def lineas_easyocr(imagen: np.ndarray) -> list[OCRLine]:
    lineas, _ = ocr_service.run_ocr(imagen)
    return lineas


def lineas_tesseract(imagen: np.ndarray) -> list[OCRLine]:
    import pytesseract

    datos = pytesseract.image_to_data(imagen, lang="spa", config=TESSERACT_CONFIG, output_type=pytesseract.Output.DICT)
    grupos: dict[tuple[int, int, int], list[int]] = {}
    for i, palabra in enumerate(datos["text"]):
        if palabra.strip() and float(datos["conf"][i]) >= 0:
            grupos.setdefault((datos["block_num"][i], datos["par_num"][i], datos["line_num"][i]), []).append(i)
    lineas = []
    for indices in grupos.values():
        indices.sort(key=lambda i: datos["left"][i])
        texto = " ".join(datos["text"][i] for i in indices)
        confianza = sum(float(datos["conf"][i]) for i in indices) / len(indices) / 100.0
        y_centro = sum(datos["top"][i] + datos["height"][i] / 2 for i in indices) / len(indices)
        lineas.append(OCRLine(texto, confianza, y_centro, min(datos["left"][i] for i in indices)))
    return sorted(lineas, key=lambda linea: (linea.y_center, linea.x_left))


MOTORES = {"easyocr": lineas_easyocr, "tesseract": lineas_tesseract}


def version_motor(motor: str) -> str:
    if motor == "easyocr":
        import easyocr
        import torch

        return f"EasyOCR {easyocr.__version__} (PyTorch {torch.__version__}, CPU)"
    import pytesseract

    return f"Tesseract {pytesseract.get_tesseract_version()} (pytesseract, '{TESSERACT_CONFIG}', idioma spa)"


# --------------------------------------------------------------------------- evaluación
def evaluar(motor: str, referencias: list[dict]) -> tuple[list[dict], dict]:
    reconocer = MOTORES[motor]
    if motor == "easyocr":
        # Carga del modelo fuera de la medición: se reporta aparte como "arranque en frío".
        inicio = time.perf_counter()
        ocr_service._reader()
        arranque = time.perf_counter() - inicio
    else:
        arranque = 0.0
    # Calentamiento con la primera imagen (no se cuenta) para medir en régimen estable.
    reconocer(preprocess_image((DATOS / referencias[0]["archivo"]).read_bytes()).image)

    filas = []
    for ref in referencias:
        contenido = (DATOS / ref["archivo"]).read_bytes()
        t0 = time.perf_counter()
        pre = preprocess_image(contenido)
        t1 = time.perf_counter()
        lineas = reconocer(pre.image)
        t2 = time.perf_counter()
        campos = extract_fields(lineas, ref["regla"])
        t3 = time.perf_counter()
        texto = "\n".join(linea.text for linea in lineas)
        ok_fecha = campos.receipt_date == ref["fecha"]
        alternativas = [normalizar(c) for c in ref["comercio"].split("|")]
        ok_comercio = normalizar(campos.merchant) in alternativas
        similitud = max(SequenceMatcher(None, normalizar(campos.merchant), a).ratio() for a in alternativas)
        ok_total = campos.total == ref["total"]
        filas.append({
            "id": ref["id"], "formato": ref["formato"], "condicion": ref["condicion"],
            "fecha_ref": ref["fecha"], "fecha_ocr": campos.receipt_date, "fecha_ok": int(ok_fecha),
            "comercio_ref": ref["comercio"], "comercio_ocr": campos.merchant, "comercio_ok": int(ok_comercio),
            "total_ref": ref["total"], "total_ocr": campos.total, "total_ok": int(ok_total),
            "comprobante_ok": int(ok_fecha and ok_comercio and ok_total),
            "similitud_comercio": round(similitud, 3),
            "rotacion_estimada": round(pre.rotation_degrees, 2),
            "t_preproceso_s": round(t1 - t0, 3), "t_ocr_s": round(t2 - t1, 3),
            "t_extraccion_s": round(t3 - t2, 4), "t_total_s": round(t3 - t0, 3),
            "texto_ocr": texto,
        })
    return filas, {"arranque_s": round(arranque, 2)}


def pct(valores) -> float:
    valores = list(valores)
    return round(100 * sum(valores) / len(valores), 1) if valores else 0.0


def resumir(filas: list[dict], extra: dict, motor: str) -> dict:
    tiempos = [f["t_total_s"] for f in filas]
    agrupar = lambda clave: {  # noqa: E731
        valor: {
            "n": len(sub), "fecha": pct(f["fecha_ok"] for f in sub), "comercio": pct(f["comercio_ok"] for f in sub),
            "total": pct(f["total_ok"] for f in sub), "comprobante": pct(f["comprobante_ok"] for f in sub),
        }
        for valor in sorted({f[clave] for f in filas})
        for sub in [[f for f in filas if f[clave] == valor]]
    }
    campos_ok = sum(f["fecha_ok"] + f["comercio_ok"] + f["total_ok"] for f in filas)
    return {
        "motor": motor, "version": version_motor(motor), "n": len(filas),
        "exactitud_fecha": pct(f["fecha_ok"] for f in filas),
        "exactitud_comercio": pct(f["comercio_ok"] for f in filas),
        "exactitud_total": pct(f["total_ok"] for f in filas),
        "exactitud_global_campos": round(100 * campos_ok / (3 * len(filas)), 1),
        "exactitud_por_comprobante": pct(f["comprobante_ok"] for f in filas),
        "similitud_comercio_media": round(statistics.mean(f["similitud_comercio"] for f in filas), 3),
        "comercio_aprox_090": pct(f["similitud_comercio"] >= 0.9 for f in filas),
        "t_medio_s": round(statistics.mean(tiempos), 2), "t_desv_s": round(statistics.pstdev(tiempos), 2),
        "t_min_s": round(min(tiempos), 2), "t_max_s": round(max(tiempos), 2),
        "t_ocr_medio_s": round(statistics.mean(f["t_ocr_s"] for f in filas), 2),
        "t_preproceso_medio_s": round(statistics.mean(f["t_preproceso_s"] for f in filas), 3),
        **extra,
        "por_formato": agrupar("formato"), "por_condicion": agrupar("condicion"),
    }


def tabla_md(resumenes: list[dict]) -> str:
    lineas = ["| Métrica | " + " | ".join(r["motor"] for r in resumenes) + " |",
              "|---|" + "---|" * len(resumenes)]
    for clave, nombre in [("exactitud_fecha", "Exactitud fecha (%)"), ("exactitud_comercio", "Exactitud comercio (%)"),
                          ("exactitud_total", "Exactitud total (%)"), ("exactitud_global_campos", "Exactitud global de campos (%)"),
                          ("exactitud_por_comprobante", "Comprobantes 100 % correctos (%)"), ("comercio_aprox_090", "Comercio con similitud >= 0,90 (%)"),
                          ("t_medio_s", "Tiempo medio por comprobante (s)"), ("t_desv_s", "Desviación estándar (s)")]:
        lineas.append(f"| {nombre} | " + " | ".join(str(r[clave]) for r in resumenes) + " |")
    return "\n".join(lineas)


def main() -> None:
    global RESULTADOS, TESSERACT_CONFIG
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--motor", choices=["easyocr", "tesseract", "ambos"], default="ambos")
    parser.add_argument("--sin-normalizacion", action="store_true",
                        help="desactiva ocr_service.normalise_ocr_spacing (reproduce la ronda 1)")
    parser.add_argument("--con-recorte", action="store_true", help="activa el recorte automático de la boleta")
    parser.add_argument("--con-realce", action="store_true",
                        help="activa CLAHE + filtro bilateral (preprocesado de las rondas 1 y 2)")
    parser.add_argument("--salida", type=Path, default=RESULTADOS)
    parser.add_argument("--calibrar-tesseract", action="store_true", help="compara los modos psm 3, 4 y 6 de Tesseract")
    args = parser.parse_args()
    RESULTADOS = args.salida
    with (DATOS / "referencia.csv").open(encoding="utf-8") as fh:
        referencias = list(csv.DictReader(fh))
    if args.sin_normalizacion:
        ocr_service.normalise_ocr_spacing = lambda texto: re.sub(r"\s+", " ", texto).strip()
    if args.con_recorte or args.con_realce:
        original = ocr_service.preprocess_image
        ocr_service.preprocess_image = lambda contenido: original(contenido, crop_document=args.con_recorte, enhance=args.con_realce)
        globals()["preprocess_image"] = ocr_service.preprocess_image
    if args.calibrar_tesseract:
        for psm in (3, 4, 6):
            TESSERACT_CONFIG = f"--oem 1 --psm {psm}"
            filas, _ = evaluar("tesseract", referencias)
            r = resumir(filas, {}, "tesseract")
            print(f"psm {psm}: global {r['exactitud_global_campos']} % | fecha {r['exactitud_fecha']} | "
                  f"comercio {r['exactitud_comercio']} | total {r['exactitud_total']}")
        return
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    motores = ["easyocr", "tesseract"] if args.motor == "ambos" else [args.motor]
    resumenes = []
    for motor in motores:
        print(f"Evaluando {motor} sobre {len(referencias)} comprobantes…", flush=True)
        filas, extra = evaluar(motor, referencias)
        with (RESULTADOS / f"detalle_{motor}.csv").open("w", newline="", encoding="utf-8") as fh:
            escritor = csv.DictWriter(fh, fieldnames=list(filas[0]))
            escritor.writeheader()
            escritor.writerows(filas)
        resumenes.append(resumir(filas, extra, motor))
        print(json.dumps({k: v for k, v in resumenes[-1].items() if not k.startswith("por_")}, ensure_ascii=False, indent=1))
    entorno = {
        "fecha_ejecucion": datetime.now().isoformat(timespec="seconds"), "python": platform.python_version(),
        "sistema": platform.platform(), "procesador": platform.processor() or platform.machine(),
        "opencv": cv2.__version__, "nucleos_cpu": __import__("os").cpu_count(),
    }
    (RESULTADOS / "resumen.json").write_text(
        json.dumps({"entorno": entorno, "resultados": resumenes}, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTADOS / "resumen.md").write_text(tabla_md(resumenes) + "\n", encoding="utf-8")
    print(tabla_md(resumenes))


if __name__ == "__main__":
    main()
