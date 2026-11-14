"""Gráfico de exactitud por campo (4 motores) y lámina de las 11 boletas reales anonimizadas."""
import csv
import json
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

AQUI = Path(__file__).resolve().parent
RES = AQUI.parent / "resultados" / "final"
plt.rcParams["font.family"] = "Liberation Serif"

resumen = {r["motor"]: r for r in json.loads((RES / "resumen.json").read_text())["resultados"]}
claves = ["exactitud_fecha", "exactitud_comercio", "exactitud_total", "exactitud_global_campos"]
etiquetas = ["Fecha", "Comercio", "Total", "Global\n(campos)"]
series = [("EasyOCR", "easyocr", "#C9D6EA"), ("Tesseract", "tesseract", "#E7B98A"), ("RapidOCR", "rapidocr", "#7FA7D1"), ("PaddleOCR", "paddleocr", "#2F5D8C")]
fig, ax = plt.subplots(figsize=(9.5, 4.8), dpi=200)
x = np.arange(len(claves)); w = 0.2
for i, (nombre, motor, color) in enumerate(series):
    valores = [resumen[motor][k] for k in claves]
    barras = ax.bar(x + (i - 1.5) * w, valores, w, label=nombre, color=color, edgecolor="#333333", linewidth=0.5)
    for b, v in zip(barras, valores):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.2, f"{v:.1f}".replace(".", ","), ha="center", va="bottom", fontsize=7.5)
ax.set_xticks(x, etiquetas); ax.set_ylim(0, 105); ax.set_ylabel("Exactitud (%)")
ax.spines[["top", "right"]].set_visible(False); ax.yaxis.grid(True, alpha=0.3); ax.set_axisbelow(True)
ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.12), fontsize=9)
fig.tight_layout(); fig.savefig(AQUI / "exactitud_por_campo.png", facecolor="white")

ids = [r["id"] for r in csv.DictReader((AQUI.parent / "datos/referencia.csv").open(encoding="utf-8"))]
archivos = {r["id"]: r["archivo"] for r in csv.DictReader((AQUI.parent / "datos/referencia.csv").open(encoding="utf-8"))}
imgs = []
for i in ids:
    im = cv2.imread(str(AQUI.parent / "datos" / archivos[i]))
    im = cv2.resize(im, (300, 430), interpolation=cv2.INTER_AREA)
    cv2.rectangle(im, (0, 396), (300, 430), (255, 255, 255), -1)
    cv2.putText(im, i, (8, 422), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2, cv2.LINE_AA)
    imgs.append(cv2.copyMakeBorder(im, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=(255, 255, 255)))
while len(imgs) % 6:
    imgs.append(np.full_like(imgs[0], 255))
filas = [np.hstack(imgs[k:k + 6]) for k in range(0, len(imgs), 6)]
cv2.imwrite(str(AQUI / "muestras_dataset.png"), np.vstack(filas))
