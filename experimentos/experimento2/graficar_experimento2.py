"""Gráfico de los tiempos del Experimento 2 (manual frente al prototipo)."""
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

AQUI = Path(__file__).resolve().parent
plt.rcParams["font.family"] = "Liberation Serif"
filas = list(csv.DictReader((AQUI / "datos_experimento2.csv").open(encoding="utf-8")))
colores = {"manual": "#E7B98A", "prototipo": "#2F5D8C"}
fig, ax = plt.subplots(figsize=(7.5, 4.4), dpi=200)
datos = [[float(f["tiempo_segundos"]) for f in filas if f["metodo"] == m] for m in ("manual", "prototipo")]
bp = ax.boxplot(datos, widths=0.45, patch_artist=True, showmeans=True, showfliers=False, medianprops={"color": "#222222"},
                meanprops={"marker": "D", "markerfacecolor": "white", "markeredgecolor": "#222222"})
for caja, m in zip(bp["boxes"], ("manual", "prototipo")):
    caja.set_facecolor(colores[m]); caja.set_edgecolor("#333333")
marcador = {"P1": "o", "P2": "s"}
for i, m in enumerate(("manual", "prototipo"), 1):
    for p in ("P1", "P2"):
        ys = [float(f["tiempo_segundos"]) for f in filas if f["metodo"] == m and f["participante"] == p]
        xs = [i + (-0.12 if p == "P1" else 0.12) + 0.02 * k for k in range(len(ys))]
        ax.scatter(xs, ys, marker=marcador[p], s=22, color="#222222", alpha=0.7, label=f"Participante {p[1]}" if i == 1 else None, zorder=3)
ax.set_xticks([1, 2]); ax.set_xticklabels(["Registro manual", "Prototipo"])
ax.set_ylabel("Tiempo por boleta (s)"); ax.set_ylim(0, 60); ax.grid(axis="y", alpha=0.3)
ax.legend(frameon=False, loc="upper right")
for sp in ("top", "right"): ax.spines[sp].set_visible(False)
fig.tight_layout()
fig.savefig(AQUI.parent / "diagramas" / "exp2_tiempos.png")
