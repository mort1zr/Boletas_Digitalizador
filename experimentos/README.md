# Experimentos del Avance 2

Evaluación reproducible del prototipo con **boletas reales anonimizadas** (capítulos 7.4 y 8 del informe).

## Contenido

| Ruta | Descripción |
|---|---|
| `datos/imagenes/` | 5 fotografías reales tomadas por el equipo. Los datos personales y de pago (tarjetas, códigos de transacción, nombres de cajeros, RUC de persona natural, QR) están cubiertos con recuadros negros. |
| `datos/referencia.csv` | Fecha, comercio (formas válidas separadas por `\|`) y total correctos, transcritos manualmente. |
| `evaluar_ocr.py` | Experimentos 1 y 3: ejecuta el pipeline real con EasyOCR y Tesseract y mide exactitud y tiempos. |
| `metricas_complementarias.py` | Intervalos de confianza de Wilson (95 %). |
| `resultados/ronda1_sin_normalizacion/` | Resultados sin la normalización del espaciado OCR. |
| `resultados/` | Resultados del prototipo actual (detalle por boleta, `resumen.json`, `resumen.md`). |
| `diagramas/` | Diagrama de flujo, arquitectura, gráfico de resultados, lámina de la muestra y capturas reales del prototipo. |

## Reproducir

Requiere las dependencias de `requirements.txt` y Tesseract 5 con español
(`apt-get install tesseract-ocr tesseract-ocr-spa` y `pip install pytesseract`).

```bash
python experimentos/evaluar_ocr.py --motor ambos
python experimentos/evaluar_ocr.py --motor ambos --sin-normalizacion --salida experimentos/resultados/ronda1_sin_normalizacion
python experimentos/metricas_complementarias.py
```

## Resultados (prototipo actual, 5 boletas reales, CPU)

| Métrica | EasyOCR | Tesseract |
|---|---|---|
| Exactitud global de campos | 26.7 % | 20.0 % |
| Boletas con los 3 campos correctos | 0.0 % | 0.0 % |
| Tiempo medio por boleta | 9.57 s | 0.97 s |

La muestra es pequeña: los porcentajes son indicativos y deben confirmarse con 20 a 30 boletas.
