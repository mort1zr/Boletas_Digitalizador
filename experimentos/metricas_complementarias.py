"""Intervalos de confianza de Wilson (95 %) para las rondas 1 y 2 sobre las boletas reales.

Uso: python experimentos/metricas_complementarias.py  (lee resultados/detalle_*.csv)
"""
import csv
import json
import math
from pathlib import Path

RES = Path(__file__).resolve().parent / "resultados"


def wilson(aciertos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    p = aciertos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(100 * max(0.0, centro - margen), 1), round(100 * min(1.0, centro + margen), 1)


salida = {}
for ronda, carpeta in [("ronda1", RES / "ronda1_sin_normalizacion"), ("ronda2", RES)]:
    for motor in ("easyocr", "tesseract"):
        filas = list(csv.DictReader((carpeta / f"detalle_{motor}.csv").open(encoding="utf-8")))
        n = len(filas)
        campos = sum(int(f["fecha_ok"]) + int(f["comercio_ok"]) + int(f["total_ok"]) for f in filas)
        salida[f"{ronda}_{motor}"] = {"campos_correctos": campos, "campos_total": 3 * n, "ic95_global": wilson(campos, 3 * n)}
(RES / "metricas_complementarias.json").write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(salida, ensure_ascii=False))
