# Ronda 5 – cuatro motores OCR sobre 12 boletas reales

Banco: R1–R6 (en el repositorio) + N1, N2, N3, N5 y M1, M2 (fotos nuevas, **no** incluidas: contienen datos personales).
Misma imagen preprocesada (gris, sin recorte ni realce) y mismas reglas de extracción para los cuatro motores.
Reproducir: `PADDLE_MODELOS=<carpeta> python experimentos/evaluar_ocr.py --motor todos --datos <carpeta_con_referencia.csv>`.

| Métrica | EasyOCR | Tesseract | RapidOCR | PaddleOCR |
|---|---|---|---|---|
| Exactitud fecha (%) | 66.7 | 50.0 | 66.7 | **100.0** |
| Exactitud comercio (%) | 33.3 | 25.0 | 41.7 | **75.0** |
| Exactitud total (%) | 50.0 | 58.3 | **100.0** | 91.7 |
| Exactitud global de campos (%) | 50.0 | 44.4 | 69.4 | **88.9** |
| Boletas con los 3 campos correctos (%) | 16.7 | 0.0 | 25.0 | **66.7** |
| Comercio con similitud >= 0,90 (%) | 41.7 | 33.3 | **83.3** | 75.0 |
| Tiempo medio por boleta (s, CPU) | 11.67 | 1.27 | **1.28** | 11.59 |

Versiones: EasyOCR 1.7.2 (PyTorch CPU), Tesseract 5 (psm 6, spa), RapidOCR 1.2.3 (ONNX Runtime 1.32, modelos PP-OCRv3),
PaddleOCR 3.7.0 (PaddlePaddle 3.3.1 CPU, modelos móviles PP-OCRv5 latín, oneDNN desactivado).

## Lectura
- PaddleOCR fue el más exacto (88.9 % de campos; 8 de 12 boletas con los tres campos correctos).
- RapidOCR fue el mejor compromiso: 69.4 %, el total perfecto (12/12) y 1.3 s por boleta; falla sobre todo en fecha y comercio.
- EasyOCR (el motor actual de la app) quedó en 50 % y es ~9 veces más lento que RapidOCR.
- Salvedades: n = 12; las reglas de extracción se ajustaron antes con salidas de EasyOCR y Tesseract (lo que, si acaso,
  favorece a esos dos); la fecha de referencia de M1 es inferida (el ticket no trae fecha de emisión explícita);
  PaddleOCR se ejecutó con modelos móviles descargados a mano y con tiempos variables (6–27 s, la boleta más larga la más lenta).
- Fallos de PaddleOCR: comercio en R1, R3 y N5; total vacío en M2.
