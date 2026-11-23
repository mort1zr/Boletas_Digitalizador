"""Gráfico de exactitud por campo (4 motores, todas las boletas) y lámina de las boletas reales anonimizadas."""
import csv
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

AQUI = Path(__file__).resolve().parent
EXP = AQUI.parent
RES = EXP / "resultados"
plt.rcParams["font.family"] = "Liberation Serif"
MOTORES = ["easyocr", "tesseract", "rapidocr", "paddleocr"]


def detalle(carpeta, motor):
    return list(csv.DictReader((RES / carpeta / f"detalle_{motor}.csv").open(encoding="utf-8")))


# Todas las boletas: R1-R11 (carpeta final) + R12-R38 (validación independiente)
filas = {m: detalle("final", m) + (detalle("validacion_independiente", m) if (RES / "validacion_independiente").exists() else []) for m in MOTORES}
n_total = len(filas["paddleocr"])


def pct(m, claves):
    ok = sum(sum(int(f[c]) for c in claves) for f in filas[m])
    return 100 * ok / (len(claves) * len(filas[m]))


grupos = [("Fecha", ["fecha_ok"]), ("Comercio", ["comercio_ok"]), ("Total", ["total_ok"]), ("Global\n(campos)", ["fecha_ok", "comercio_ok", "total_ok"])]
series = [("EasyOCR", "easyocr", "#C9D6EA"), ("Tesseract", "tesseract", "#E7B98A"), ("RapidOCR", "rapidocr", "#7FA7D1"), ("PaddleOCR", "paddleocr", "#2F5D8C")]
fig, ax = plt.subplots(figsize=(9.5, 4.8), dpi=200)
x = np.arange(len(grupos)); w = 0.2
for i, (nombre, motor, color) in enumerate(series):
    valores = [pct(motor, claves) for _, claves in grupos]
    barras = ax.bar(x + (i - 1.5) * w, valores, w, label=nombre, color=color, edgecolor="#333333", linewidth=0.5)
    for b, v in zip(barras, valores):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.2, f"{v:.1f}".replace(".", ","), ha="center", va="bottom", fontsize=7.5)
ax.set_xticks(x, [g for g, _ in grupos]); ax.set_ylim(0, 105); ax.set_ylabel(f"Exactitud (%) · {n_total} boletas")
ax.spines[["top", "right"]].set_visible(False); ax.yaxis.grid(True, alpha=0.3); ax.set_axisbelow(True)
ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.12), fontsize=9)
fig.tight_layout(); fig.savefig(AQUI / "exactitud_por_campo.png", facecolor="white")

# Lámina de la muestra (las imágenes de R12-R38 están en datos_privado, fuera de Git)
refs = list(csv.DictReader((EXP / "datos/referencia.csv").open(encoding="utf-8")))
if (EXP / "datos_privado/referencia.csv").exists():
    refs += [dict(r, _privado=True) for r in csv.DictReader((EXP / "datos_privado/referencia.csv").open(encoding="utf-8"))]
imgs = []
for r in refs:
    ruta = EXP / ("datos_privado" if r.get("_privado") else "datos") / r["archivo"]
    if not ruta.exists():
        continue
    im = cv2.imread(str(ruta))
    im = cv2.resize(im, (220, 316), interpolation=cv2.INTER_AREA)
    cv2.rectangle(im, (0, 290), (220, 316), (255, 255, 255), -1)
    cv2.putText(im, r["id"], (6, 311), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 2, cv2.LINE_AA)
    imgs.append(cv2.copyMakeBorder(im, 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=(255, 255, 255)))
columnas = 8
while len(imgs) % columnas:
    imgs.append(np.full_like(imgs[0], 255))
cv2.imwrite(str(AQUI / "muestras_dataset.png"), np.vstack([np.hstack(imgs[k:k + columnas]) for k in range(0, len(imgs), columnas)]))
