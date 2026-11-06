# Experimentos del Avance 2

Evaluación reproducible del prototipo (capítulos 7.4 y 8 del informe).

> **Importante:** los 24 comprobantes de `datos/` son **sintéticos** (comercios, RUC, DNI y montos ficticios).
> Los resultados no deben generalizarse a comprobantes reales; la validación con comprobantes reales
> anonimizados está pendiente.

## Contenido

| Ruta | Descripción |
|---|---|
| `generar_dataset.py` | Genera los comprobantes (formatos A, B y C; 6 condiciones de captura; semilla 2026). |
| `datos/imagenes/` | Las 24 imágenes JPG generadas. |
| `datos/referencia.csv` | Valores correctos de fecha, comercio y total de cada comprobante. |
| `evaluar_ocr.py` | Experimentos 1 y 3: ejecuta el pipeline real con EasyOCR y Tesseract y mide exactitud y tiempos. |
| `metricas_complementarias.py` | Coincidencia aproximada del comercio e intervalos de confianza de Wilson (95 %). |
| `resultados/ronda1_sin_normalizacion/` | Resultados antes de la normalización del espaciado OCR. |
| `resultados/` | Resultados de la ronda 2 (detalle por comprobante, `resumen.json`, `resumen.md`). |
| `diagramas/` | Diagrama de flujo, arquitectura, gráficos, láminas y capturas reales del prototipo. |

## Reproducir

Requiere las dependencias de `requirements.txt` y, para la comparación, Tesseract 5 con el idioma español
(`apt-get install tesseract-ocr tesseract-ocr-spa` y `pip install pytesseract`).

```bash
python experimentos/generar_dataset.py
python experimentos/evaluar_ocr.py --motor ambos
python experimentos/metricas_complementarias.py
```

## Resultados (ronda 2, CPU)

| Métrica | EasyOCR | Tesseract |
|---|---|---|
| Exactitud global de campos | 73,6 % | 93,1 % |
| Comprobantes con los 3 campos correctos | 41,7 % | 83,3 % |
| Tiempo medio por comprobante | 13,59 s | 0,64 s |
