# Ronda 4 – cinco boletas nuevas (fotos de 4080×2296 px, fondo oscuro)

Las imágenes **no** se incluyen en el repositorio: contienen datos personales (nombre de una persona natural,
RUC 10… con DNI, DNI y nombre del cliente) y requieren anonimización antes de publicarse.
Una de las cinco (N4) es la misma boleta que R1 en otra foto, por lo que la muestra independiente es de **4 boletas**.

| Id | Tipo | Dificultad |
|---|---|---|
| N1 | Boleta de persona natural | sombra; manuscrito visible al reverso |
| N2 | Voucher Openpay BBVA | brillo en la parte alta |
| N3 | Boleta de supermercado | la fecha solo aparece al pie, sin etiqueta |
| N4 | Voucher Culqi (= R1) | repetida |
| N5 | Voucher Niubiz | borde superior rasgado; importe sin la palabra «TOTAL» |

## A. Muestra independiente (antes de ajustar con ellas) – 5 boletas × 3 campos = 15

| Preprocesado | EasyOCR | Tesseract |
|---|---|---|
| En gris (valor por defecto desde la ronda 3) | 9 / 15 | 8 / 15 |
| Con realce CLAHE + bilateral (prototipo anterior) | 8 / 15 | 9 / 15 |

- **Fecha: 5/5 con ambos motores** (incluida N3, sin etiqueta «Fecha»).
- La diferencia entre gris y realce **no se confirma** en esta muestra (±1 campo): la conclusión de la ronda 3 no
  queda respaldada ni refutada; hace falta una muestra mayor.
- Fallos: N1 sin total (el encabezado de columna «P.U. TOTAL» competía con «TOTAL: S/ 129.00»); N5 sin total (importe
  «S/ 175.20» sin etiqueta); N2 con EasyOCR leyó 27.00 en lugar de 50.00 (error de lectura).

## B. Tras corregir esos dos fallos de extracción (ya no es independiente para N1 y N5) – 15 campos

| Motor | Campos correctos |
|---|---|
| EasyOCR | 11 / 15 (fecha 5, comercio 2, total 4) |
| Tesseract | 10 / 15 (fecha 5, comercio 0, total 5) |

- Comercio exacto: EasyOCR 2/5 y Tesseract 0/5. Cuando el OCR no es seguro el sistema deja el campo vacío en vez de
  adivinar. Con Tesseract la similitud de texto fue 0.6–0.83 en 4 de 5 (p. ej. «NIUDIZ» por «NIUBIZ»).
- Regresión sobre R1–R6: sin cambios (EasyOCR 33.3 %, Tesseract 44.4 % de campos correctos).
- Los cambios de extracción: ignorar el encabezado de columna «TOTAL», preferir el importe en la misma línea, aceptar el
  único importe aislado solo en vouchers de POS (con aviso), y priorizar el nombre impreso justo encima del RUC.

Advertencia: el apartado B se ajustó con las mismas fotos que lo miden; es una verificación de que los fallos se
corrigieron, no una estimación de exactitud. Para el informe, la cifra válida es la del apartado A.
