# Digitalizador inteligente de boletas de compra

Prototipo local en Python con Streamlit, OpenCV, EasyOCR y SQLite. La herramienta ayuda a registrar **fecha, comercio y total**, pero exige que una persona revise y confirme los valores antes de guardarlos.

## Funcionalidades incluidas

- **HU-01:** autenticación local mediante `st.session_state`. La contraseña se crea en una terminal, se oculta al escribirla y se almacena como hash PBKDF2-HMAC-SHA256 con salt aleatorio; no hay credenciales predefinidas en el código.
- **HU-02 / HU-03:** carga individual JPG/JPEG/PNG con límite de 10 MB, vista previa, corrección de inclinación y contraste con OpenCV. El original no se sobrescribe.
- **HU-04 / HU-07 / HU-11:** EasyOCR preentrenado para español e inglés y reglas heurísticas diferenciadas para Formato A y B. Los campos ausentes o dudosos permanecen vacíos.
- **HU-05 / HU-06:** formulario editable, validaciones para fecha, comercio y total positivo, confirmación explícita y guardado persistente en SQLite. La acción de guardado es idempotente dentro de la misma carga/sesión.
- **HU-08 / HU-09 / HU-10:** consulta ordenada por fecha descendente, filtros combinables por rango inclusivo y comercio, exportación de las filas filtradas a CSV con total a dos decimales.
- **HU-13:** selección de una fila de la tabla para abrir la imagen, el texto original de EasyOCR, los candidatos propuestos y los valores confirmados.

## Requisitos

- Python 3.10 o superior (recomendado: Python 3.11 o 3.12).
- Conexión a Internet durante la primera ejecución de EasyOCR para descargar sus modelos preentrenados. No se entrena ningún modelo propio.
- Los registros, las imágenes y el archivo de usuario se almacenan localmente en `data/` por defecto.

## Instalación y ejecución en Windows (PowerShell)

```powershell
cd digitalizador_boletas
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python create_user.py
streamlit run main.py
```

En `create_user.py` se solicita usuario y contraseña en la terminal; la contraseña se introduce oculta. La cuenta local se guarda en `data/users.json` con salt y hash, no en texto plano. Si se olvida la contraseña, vuelve a ejecutar `python create_user.py` y acepta reemplazar la cuenta.

### Linux / macOS

```bash
cd digitalizador_boletas
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python create_user.py
streamlit run main.py
```

El primer procesamiento puede tardar más mientras EasyOCR descarga los modelos. Para detener Streamlit, usa `Ctrl+C` en la terminal.

## Estructura

```text
 digitalizador_boletas/
 ├── main.py             # Entrada de Streamlit
 ├── ui.py               # Login, carga/revisión, dashboard, CSV y evidencia
 ├── ocr_service.py      # OpenCV, EasyOCR y reglas de extracción A/B
 ├── repository.py       # SQLite y persistencia atómica de imágenes
 ├── auth_service.py     # PBKDF2, verificación y lectura de la cuenta
 ├── create_user.py      # Alta de cuenta local interactiva
 ├── app_config.py       # Rutas, límite de carga y carpetas
 ├── tests/
 │   └── test_ocr_service.py
 ├── requirements.txt
 └── data/               # Se crea automáticamente; excluida de Git
     ├── users.json
     ├── receipts.sqlite3
     └── images/
```

## Pipeline OpenCV: parámetros exactos

1. **Decodificación:** `cv2.imdecode(..., cv2.IMREAD_COLOR)`.
2. **Escalado:** si el lado más largo supera `2400 px`, se redimensiona proporcionalmente con `cv2.INTER_AREA`. No se recortan regiones de la boleta.
3. **Escala de grises:** `cv2.cvtColor(..., cv2.COLOR_BGR2GRAY)`.
4. **Detección de inclinación:** `cv2.Canny(gray, 50, 150, apertureSize=3)` seguido de `cv2.HoughLinesP(edges, rho=1, theta=pi/180, threshold=50, minLineLength=max(30, 0.15*ancho), maxLineGap=20)`. Solo se consideran líneas con ángulo absoluto de hasta `15°`. Se usa la mediana ponderada por longitud. Las rotaciones estimadas menores que `0.15°` se ignoran.
5. **Rotación:** `cv2.getRotationMatrix2D` y `cv2.warpAffine` con `cv2.INTER_CUBIC`, lienzo expandido para evitar recortes y fondo blanco (`255`).
6. **Contraste local:** `cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)`.
7. **Denoising:** `cv2.bilateralFilter(image, d=5, sigmaColor=35, sigmaSpace=35)`.
8. **Codificación de salida:** PNG con `cv2.imencode('.png', ..., [cv2.IMWRITE_PNG_COMPRESSION, 3])`; esta copia se entrega a EasyOCR y se conserva por separado para evidencia.

Los parámetros son punto de partida reproducible; deben compararse con imágenes originales y procesadas del conjunto de ajuste real antes de afirmar que mejoran la exactitud.

## Reglas iniciales para los formatos A y B

- **Formato A:** prioriza una etiqueta explícita (por ejemplo, `TOTAL A PAGAR`, `IMPORTE TOTAL`, `TOTAL GENERAL` o `TOTAL`). Ignora líneas etiquetadas como subtotal, IGV/IVA/impuestos, descuento, vuelto/cambio, efectivo/recibido, propina e identificadores RUC/DNI. Si no encuentra un total etiquetado inequívoco, deja el campo vacío.
- **Formato B:** aplica primero las mismas reglas para etiquetas de total. Si no hay una etiqueta identificable, permite como alternativa un monto con moneda o decimales en el tramo final del ticket, excluyendo impuestos, subtotal, vuelto y recibido.
- **Fecha:** soporta patrones día/mes/año, día-mes-año, día.mes.año y año-mes-día; valida la fecha del calendario y favorece una etiqueta de fecha de emisión. Si dos fechas tienen puntuaciones semejantes y no hay señales suficientes para decidir, deja el campo vacío.
- **Comercio:** busca un candidato en las líneas iniciales y excluye etiquetas comunes del comprobante, identificadores y datos de contacto. Si ninguna línea parece un comercio, deja el campo vacío.

> **Importante:** los documentos de planificación adjuntos describen dos formatos, pero no contienen imágenes de boletas ni definen el diseño exacto de A y B. Estas reglas son una base funcional, no una garantía de extracción correcta. Para cumplir de forma verificable el criterio de tres ejemplos por formato, agreguen ejemplos anonimizados y ajusten/proben las reglas con los valores de referencia del Product Owner. La revisión humana sigue siendo obligatoria.

## Base de datos y trazabilidad

SQLite conserva fecha, comercio, total en céntimos enteros, instante de registro, ubicación de la imagen original y procesada, texto completo OCR, los tres candidatos iniciales, formato utilizado e identificador único de la acción. Los valores finales se almacenan por separado de los propuestos. El campo monetario se representa en céntimos para evitar errores de punto flotante; la UI y el CSV lo muestran con dos decimales.

El CSV incluye los encabezados `id,fecha,comercio,total`, usa UTF-8 con BOM para facilitar la apertura en hojas de cálculo y exporta solo el subconjunto filtrado. Se neutralizan nombres de comercio que comiencen con caracteres de fórmula de hoja de cálculo.

## Pruebas

```bash
pytest -q
```

Las pruebas incluidas comprueban formatos numéricos, que el total no se confunda con subtotal/IGV/vuelto, el fallback del Formato B y el tratamiento conservador de fechas ambiguas. La verificación funcional de EasyOCR debe hacerse con boletas reales del conjunto de ajuste.

## Limitaciones conocidas

- Es un prototipo local, no multiusuario ni desplegado en la nube.
- El OCR depende de la calidad, iluminación, tipografía y disposición del recibo; los modelos se descargan en el primer uso.
- No valida comprobantes con SUNAT, no procesa PDF ni lotes, y no extrae líneas de productos, acorde con el alcance MVP descrito en el plan Scrum.
- La autenticación es de demostración para uso local; no sustituye un sistema de identidad para producción.
