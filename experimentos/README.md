# Experimentos del informe final

Evaluación reproducible del prototipo con **11 boletas reales anonimizadas** (capítulos 7.4 y 8 del informe).

## Contenido

| Ruta | Descripción |
|---|---|
| `datos/imagenes/` | 11 fotografías reales (R1 a R11) tomadas por el equipo. Los datos personales y de pago (tarjetas, DNI, códigos de transacción, nombres de personas, RUC de persona natural, códigos QR y de barras) están cubiertos con recuadros negros. |
| `datos/referencia.csv` | Fecha, comercio (formas válidas separadas por `\|`) y total correctos, transcritos manualmente. La fecha de R10 es inferida. |
| `evaluar_ocr.py` | Experimentos 1 y 3: ejecuta el pipeline real con EasyOCR (opcional), Tesseract, RapidOCR y PaddleOCR y mide exactitud y tiempos. |
| `comparar_preprocesado.py` | Experimento 4: compara cuatro formas de preparar la imagen. |
| `metricas_complementarias.py` | Intervalos de confianza de Wilson (95 %). |
| `experimento2/` | Protocolo, plantilla y script del Experimento 2 (tiempo de registro con usuarios); **no se ejecutó**. |
| `resultados/final/` | Resultados del prototipo actual con los cuatro motores (detalle por boleta, `resumen.json`, `resumen.md`). |
| `resultados/final_previo/` | Mismos motores antes de la última corrección de las reglas de fecha y de importe en letras. |
| `resultados/ronda1_sin_normalizacion/`, `resultados/*.md` | Rondas anteriores (cinco boletas, preprocesado, boletas nuevas y comparación de motores). |
| `diagramas/` | Diagrama de flujo, arquitectura, gráfico de resultados, lámina de la muestra y capturas reales del prototipo. |

## Reproducir

Requiere las dependencias de `requirements.txt` y Tesseract 5 con español
(`apt-get install tesseract-ocr tesseract-ocr-spa` y `pip install pytesseract`). Para comparar con
RapidOCR y EasyOCR: `pip install rapidocr-onnxruntime easyocr`.

```bash
python experimentos/evaluar_ocr.py --motor todos --salida experimentos/resultados/final
python experimentos/metricas_complementarias.py
python experimentos/comparar_preprocesado.py paddleocr
```

Si los modelos de PaddleOCR ya están descargados, define `PADDLE_MODELOS` con la carpeta que contiene
`PP-OCRv5_mobile_det_infer` y `latin_PP-OCRv5_mobile_rec_infer`.

## Resultados (prototipo actual, 11 boletas reales, CPU, imagen en grises)

| Métrica | PaddleOCR | RapidOCR | EasyOCR | Tesseract |
|---|---|---|---|---|
| Exactitud global de campos | 90.9 % | 69.7 % | 48.5 % | 48.5 % |
| Boletas con los 3 campos correctos | 8 de 11 | 3 de 11 | 1 de 11 | 1 de 11 |
| Tiempo medio por boleta | 11.2 s | 1.2 s | 12.2 s | 1.3 s |

La muestra es pequeña y las reglas de extracción se ajustaron mirando fallos de estas mismas boletas:
los porcentajes son indicativos y deben confirmarse con boletas nuevas.
