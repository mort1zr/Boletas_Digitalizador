# Ronda 3 – mejoras de extracción y preprocesado (6 boletas reales)

Conjunto: R1–R5 (rondas anteriores) + **R6** (Tambo, foto vertical sobre madera, original HEIC de Samsung).
R6 se usó para diseñar las mejoras, por lo que **no es una muestra independiente**. Estos números sirven para
decidir el diseño, no para afirmar una exactitud final: hay que validarlos con boletas nuevas.

## Campos correctos (de 6 boletas × 3 campos = 18 por variante)

| Preprocesado | EasyOCR | Tesseract |
|---|---|---|
| Sin recorte, con realce (CLAHE + bilateral; prototipo anterior) | 4 / 18 | 5 / 18 |
| Con recorte, con realce | 4 / 18 | 4 / 18 |
| Con recorte, en gris | 6 / 18 | 5 / 18 |
| **Sin recorte, en gris (nuevo valor por defecto)** | **7 / 18** | **8 / 18** |

Reproducir: `python experimentos/comparar_preprocesado.py easyocr|tesseract`.

## Medición oficial con el valor por defecto nuevo (`evaluar_ocr.py --motor ambos`)

| Métrica | EasyOCR | Tesseract |
|---|---|---|
| Exactitud fecha (%) | 33.3 | 66.7 |
| Exactitud comercio (%) | 16.7 | 16.7 |
| Exactitud total (%) | 50.0 | 50.0 |
| Exactitud global de campos (%) | 33.3 | 44.4 |
| Boletas con los 3 campos correctos (%) | 0.0 | 0.0 |
| Tiempo medio por boleta (s) | 11.16 | 0.90 |

Referencia sobre las mismas 6 boletas con el prototipo anterior: EasyOCR 22.2 % y Tesseract 27.8 % de campos correctos.

## Lectura honesta

- Quitar el realce de contraste fue lo que más ayudó, con ambos motores: amplifica el grano de la impresión térmica.
- El recorte automático de la boleta no fue consistente (ayudó al total en algunas fotos y perjudicó la fecha en otras),
  así que queda como opción (`crop_document=True`) y no como valor por defecto.
- Ninguna boleta llega aún a los 3 campos correctos; con n = 6 las diferencias son pequeñas y pueden ser ruido.
- Las reglas nuevas (fecha con letras confundidas, razón social junto al RUC, total contrastado con el importe en letras)
  están cubiertas por pruebas unitarias; su efecto sobre boletas reales depende de que el OCR lea esas líneas.
