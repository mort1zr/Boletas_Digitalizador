"""Dibuja el diagrama de arquitectura por capas (Figura del capítulo 7.3)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

plt.rcParams["font.family"] = "Liberation Serif"
CAPAS = [
    ("1. Presentación", "Streamlit · ui.py", "#E3EBF6", ["Inicio de sesión\n(PBKDF2)", "Carga de archivo\no cámara", "Revisión y\nconfirmación", "Consulta y\nevidencia"]),
    ("2. Procesamiento\nde imágenes", "OpenCV · ocr_service.py", "#FFF1D6", ["Escalado\n≤ 2400 px", "Grises + inclinación\n(Canny + Hough)", "Contraste\nlocal CLAHE", "Filtro\nbilateral"]),
    ("3. Reconocimiento\nOCR", "EasyOCR · preentrenado", "#FFE6C7", ["Detección de texto\nCRAFT", "Reconocimiento\nCRNN (es/en)", "Agrupación\nen líneas"]),
    ("4. Extracción de\ninformación", "reglas · ocr_service.py", "#FDE2D4", ["Fecha\n(patrones + etiquetas)", "Comercio\n(encabezado)", "Total\n(etiquetas A/B)"]),
    ("5. Validación\nde datos", "receipt_service.py", "#E2F1E2", ["Reglas de\nvalidación", "Confirmación\nexplícita", "Guardado\nidempotente"]),
    ("6. Persistencia", "repository.py", "#EDE5F4", ["SQLite\n(propuestos + confirmados)", "Imágenes original\ny procesada", "Escritura\natómica"]),
    ("7. Consulta y\nexportación", "repository.py ·\nreceipt_service.py", "#ECECEC", ["Filtros por\nfecha y comercio", "Vista de\nevidencia OCR", "Exportación\nCSV UTF-8"]),
]
FLUJOS = ["imagen (bytes)", "imagen procesada", "líneas + confianza", "campos propuestos", "campos confirmados", "registros"]

fig, ax = plt.subplots(figsize=(11, 12.5), dpi=200)
ax.set_xlim(0, 110); ax.set_ylim(0, 128); ax.axis("off")
alto, sep, x0, ancho = 14.2, 3.6, 2, 88
for i, (titulo, sub, color, comps) in enumerate(CAPAS):
    y = 124 - (i + 1) * alto - i * sep
    ax.add_patch(FancyBboxPatch((x0, y), ancho, alto, boxstyle="round,pad=0.4,rounding_size=1.5", fc=color, ec="#4A5A72", lw=1.1))
    ax.text(x0 + 1.5, y + alto - 2.2, titulo, fontsize=12, fontweight="bold", va="top", color="#1F2A3A")
    ax.text(x0 + 1.5, y + alto - 2.2 - 2.9 * (titulo.count("\n") + 1), sub, fontsize=9.5, va="top", style="italic", color="#3A4A60")
    n = len(comps); zona_x = x0 + 25; zona_w = ancho - 26.5; w = (zona_w - (n - 1) * 1.6) / n
    for j, c in enumerate(comps):
        cx = zona_x + j * (w + 1.6)
        ax.add_patch(FancyBboxPatch((cx, y + 1.6), w, alto - 3.2, boxstyle="round,pad=0.25,rounding_size=1.0", fc="white", ec="#4A5A72", lw=0.9))
        ax.text(cx + w / 2, y + alto / 2, c, fontsize=9.3, ha="center", va="center", color="#1F2A3A")
    if i < len(CAPAS) - 1:
        ya, yb = y - 0.2, y - sep + 0.2
        ax.add_patch(FancyArrowPatch((x0 + 12, ya), (x0 + 12, yb), arrowstyle="-|>", mutation_scale=12, color="#33445C", lw=1.3))
        ax.text(x0 + 13.5, (ya + yb) / 2, FLUJOS[i], fontsize=8.8, va="center", color="#33445C", style="italic")
# Banda transversal
ax.add_patch(FancyBboxPatch((x0 + ancho + 3, 124 - 7 * alto - 6 * sep), 15, 7 * alto + 6 * sep, boxstyle="round,pad=0.4,rounding_size=1.5", fc="#F5F7FA", ec="#7A8CA8", lw=1.1, ls="--"))
ax.text(x0 + ancho + 10.5, 124 - (7 * alto + 6 * sep) / 2,
        "TRANSVERSAL\n\nAutenticación local\nPBKDF2-SHA256\n\nConfiguración\napp_config.py\n\nPruebas\nautomatizadas\n(pytest, 144)\n\nIntegración\ncontinua\n(GitHub Actions)\n\nDespliegue\nDocker",
        fontsize=9.2, ha="center", va="center", color="#1F2A3A")
fig.savefig(Path(__file__).with_suffix(".png"), bbox_inches="tight", facecolor="white")
