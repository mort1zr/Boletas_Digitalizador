# Experimentos del informe final

Evaluación reproducible del prototipo con **38 boletas reales anonimizadas** (capítulos 7.4 y 8 del informe): 11 con las que se ajustaron las reglas (R1 a R11) y 27 de validación independiente (R12 a R38).

## Contenido

| Ruta | Descripción |
|---|---|
| `datos_privado/` | Referencias (`referencia.csv`) de las 27 boletas de validación (R12 a R38). Sus imágenes anonimizadas **no están en Git** (repositorio público) y se entregan aparte en el archivo de datos; se esperan en `datos_privado/imagenes/`. |
| `datos/imagenes/` | 11 fotografías reales (R1 a R11) tomadas por el equipo. Los datos personales y de pago (tarjetas, DNI, códigos de transacción, nombres de personas, RUC de persona natural, códigos QR y de barras) están cubiertos con recuadros negros. |
| `datos/referencia.csv` | Fecha, comercio (formas válidas separadas por `\|`) y total correctos, transcritos manualmente. La fecha de R10 es inferida. |
| `evaluar_ocr.py` | Experimentos 1 y 3: ejecuta el pipeline real con EasyOCR (opcional), Tesseract, RapidOCR y PaddleOCR y mide exactitud y tiempos. |
| `comparar_preprocesado.py` | Experimento 4: compara cuatro formas de preparar la imagen. |
| `metricas_complementarias.py` | Intervalos de confianza de Wilson (95 %). |
| `experimento2/` | Experimento 2 (tiempo de registro manual frente al prototipo con dos participantes): protocolo, datos medidos (`datos_experimento2.csv`), libro de registro, script de análisis y gráfico. |
| `resultados/final/` | Resultados de los cuatro motores con R1 a R11 (detalle por boleta, `resumen.json`, `resumen.md`). |
| `resultados/validacion_independiente/` | Resultados de los cuatro motores con R12 a R38, medidas sin ajustar ninguna regla. |
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

## Resultados (prototipo actual, CPU, imagen en grises)

| Métrica | PaddleOCR | RapidOCR | EasyOCR | Tesseract |
|---|---|---|---|---|
| Exactitud global, 38 boletas | 85.1 % | 70.2 % | 48.2 % | 49.1 % |
| Exactitud global, ajuste (R1–R11) | 90.9 % | 69.7 % | 48.5 % | 48.5 % |
| Exactitud global, validación independiente (R12–R38) | 82.7 % | 70.4 % | 48.1 % | 49.4 % |
| Tiempo medio por boleta | 11.6 s | 1.3 s | 13.1 s | 1.4 s |

Las reglas se ajustaron con R1 a R11; R12 a R38 se midieron sin tocarlas. La muestra es moderada: los
porcentajes son indicativos. Para evaluar R12 a R38 hay que copiar sus imágenes anonimizadas a
`datos_privado/imagenes/` y ejecutar `python experimentos/evaluar_ocr.py --motor todos --datos experimentos/datos_privado`.
