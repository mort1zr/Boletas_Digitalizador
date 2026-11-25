"""Experimento 2: tiempo de registro manual frente al prototipo.

Uso: python experimentos/experimento2/analizar_experimento2.py [archivo.csv]

El archivo (plantilla_tiempos.csv) tiene una fila por boleta y participante, con la columna
``metodo`` = manual | prototipo, el tiempo en segundos medido con cronómetro desde que se toma la
boleta hasta que el registro queda guardado (en el prototipo incluye la revisión y corrección), y
el número de campos erróneos en los datos finales. Se alterna el método que se usa primero entre
participantes para controlar el aprendizaje. Calcula la media por método, la reducción de tiempo
y los errores. No inventa datos: si faltan tiempos, lo indica.
"""
import csv
import statistics
import sys
from pathlib import Path

ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("plantilla_tiempos.csv")
filas = [f for f in csv.DictReader(ruta.open(encoding="utf-8")) if f["tiempo_segundos"].strip()]
if not filas:
    sys.exit("No hay tiempos registrados: completa la columna tiempo_segundos con las mediciones reales.")
por = {"manual": [], "prototipo": []}
errores = {"manual": 0, "prototipo": 0}
for f in filas:
    por[f["metodo"]].append(float(f["tiempo_segundos"]))
    errores[f["metodo"]] += int(f["errores_en_datos_finales"] or 0)
for metodo, v in por.items():
    if not v:
        sys.exit(f"Faltan mediciones del método {metodo}.")
media = {m: statistics.mean(v) for m, v in por.items()}
dev = {m: statistics.pstdev(v) for m, v in por.items()}
reduccion = 100 * (media["manual"] - media["prototipo"]) / media["manual"]
print(f"Boletas medidas: manual {len(por['manual'])}, prototipo {len(por['prototipo'])}")
for m in por:
    print(f"{m:10s} tiempo medio {media[m]:.1f} s ± {dev[m]:.1f}  | errores en datos finales: {errores[m]}")
print(f"Reducción de tiempo: {reduccion:.1f} %")
