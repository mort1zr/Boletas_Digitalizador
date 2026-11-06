"""Gráfico de exactitud por campo y lámina de ejemplos del conjunto sintético."""
import json
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

AQUI = Path(__file__).resolve().parent
RES = AQUI.parent / "resultados"
plt.rcParams["font.family"] = "Liberation Serif"

r1 = {r["motor"]: r for r in json.loads((RES / "ronda1_sin_normalizacion/resumen.json").read_text())["resultados"]}
r2 = {r["motor"]: r for r in json.loads((RES / "resumen.json").read_text())["resultados"]}
claves = ["exactitud_fecha", "exactitud_comercio", "exactitud_total", "exactitud_global_campos", "exactitud_por_comprobante"]
etiquetas = ["Fecha", "Comercio", "Total", "Global\n(campos)", "Comprobante\ncompleto"]
series = [("EasyOCR – ronda 1", r1["easyocr"], "#C9D6EA"), ("EasyOCR – ronda 2", r2["easyocr"], "#4A6FA5"), ("Tesseract – ronda 2", r2["tesseract"], "#D9822B")]
fig, ax = plt.subplots(figsize=(9, 4.6), dpi=200)
x = np.arange(len(claves)); w = 0.26
for i, (nombre, datos, color) in enumerate(series):
    valores = [datos[k] for k in claves]
    barras = ax.bar(x + (i - 1) * w, valores, w, label=nombre, color=color, edgecolor="#333333", linewidth=0.5)
    for b, v in zip(barras, valores):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.2, f"{v:.1f}".replace(".", ","), ha="center", va="bottom", fontsize=8)
ax.set_xticks(x, etiquetas); ax.set_ylim(0, 110); ax.set_ylabel("Exactitud (%)")
ax.spines[["top", "right"]].set_visible(False); ax.yaxis.grid(True, alpha=0.3); ax.set_axisbelow(True)
ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.12), fontsize=9)
fig.tight_layout(); fig.savefig(AQUI / "exactitud_por_campo.png", facecolor="white")

archivos = ["A02_inclinada", "A04_desenfoque", "B01_perspectiva", "B04_ruido", "C01_iluminacion", "C03_ideal"]
imgs = []
for nombre in archivos:
    im = cv2.imread(str(AQUI.parent / "datos/imagenes" / f"{nombre}.jpg"))
    im = cv2.resize(im, (360, 480))
    cv2.rectangle(im, (0, 440), (360, 480), (255, 255, 255), -1)
    cv2.putText(im, nombre, (10, 468), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (20, 20, 20), 2, cv2.LINE_AA)
    imgs.append(im)
borde = lambda im: cv2.copyMakeBorder(im, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=(255, 255, 255))  # noqa: E731
lamina = np.vstack([np.hstack([borde(i) for i in imgs[:3]]), np.hstack([borde(i) for i in imgs[3:]])])
cv2.imwrite(str(AQUI / "muestras_dataset.png"), lamina)
