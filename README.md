# Digitalizador inteligente de boletas de compra

Prototipo local en Python con Streamlit, OpenCV, PaddleOCR y SQLite. La herramienta ayuda a registrar **fecha, comercio y total**, pero exige que una persona revise y confirme los valores antes de guardarlos.

## Inicio rápido

1. Instala Python 3.11 o 3.12 y crea un entorno virtual (ver «Instalación y ejecución»).
2. `pip install -r requirements.txt`
3. `python create_user.py` (crea el usuario y la contraseña; la contraseña no se muestra al escribirla).
4. `streamlit run main.py` y abre <http://localhost:8501>.
5. Inicia sesión, sube la foto de una boleta (JPG, PNG, HEIC o cámara), revisa los tres campos propuestos, corrige lo que haga falta y confirma.

Con Docker: `docker compose build`, `docker compose run --rm app python create_user.py` y `docker compose up -d` (ver «Ejecución con Docker»).
La primera lectura descarga los modelos de PaddleOCR (unos 13 MB) y tarda más.

**Pruebas:** `pytest -q` (269 pruebas; una requiere los modelos de PaddleOCR y se omite si no están).
**Experimentos del informe:** `experimentos/README.md`.

### Resultados principales (38 boletas reales anonimizadas)

| Motor | Exactitud global (fecha, comercio y total) | Tiempo medio por boleta (CPU) |
|---|---|---|
| **PaddleOCR (el que usa el prototipo)** | **85,1 %** (82,7 % en las 27 boletas de validación independiente) | 11,6 s |
| RapidOCR | 70,2 % | 1,3 s |
| Tesseract | 49,1 % | 1,4 s |
| EasyOCR | 48,2 % | 13,1 s |

En el Experimento 2, con dos participantes, el tiempo de registro por boleta bajó de 39,2 s (manual) a 20,1 s (prototipo), un 48,8 %.

## Funcionalidades incluidas

- **HU-01:** autenticación local mediante `st.session_state`. La contraseña se crea en una terminal, se oculta al escribirla y se almacena como hash PBKDF2-HMAC-SHA256 con salt aleatorio; no hay credenciales predefinidas en el código.
- **HU-02 / HU-03:** carga individual JPG/JPEG/PNG **o HEIC/HEIF (el formato por defecto de iPhone y varios Samsung; se convierte a JPG al subirla, sin que el usuario haga nada)** con límite de 10 MB **o captura con la cámara** (webcam o cámara del celular desde el navegador), vista previa, corrección de inclinación y contraste con OpenCV. El original no se sobrescribe.
- **HU-04 / HU-07 / HU-11:** PaddleOCR preentrenado (alfabeto latino: español con tildes y ñ) y reglas heurísticas diferenciadas para Formato A y B. Los campos ausentes o dudosos permanecen vacíos.
- **HU-05 / HU-06:** formulario editable, validaciones para fecha, comercio y total positivo, confirmación explícita y guardado persistente en SQLite. La acción de guardado es idempotente dentro de la misma carga/sesión.
- **HU-08 / HU-09 / HU-10:** consulta ordenada por fecha descendente, filtros combinables por rango inclusivo y comercio, exportación de las filas filtradas a CSV con total a dos decimales.
- **HU-13:** selección de una fila de la tabla para abrir la imagen, el texto original reconocido por PaddleOCR, los candidatos propuestos y los valores confirmados.
- **Privacidad:** las imágenes y el texto OCR se **cifran en reposo** (Fernet) y, antes de guardar el texto, se **enmascaran** el DNI, los números de tarjeta y los RUC de persona natural (ver «Privacidad y cifrado»).
- **Preguntas en lenguaje natural (pestaña 💬 Preguntar):** «¿Cuánto gasté en Makro durante octubre?». La pregunta se traduce a un plan de consulta y **las cifras las calcula el código** sobre tus registros, no un modelo; con `ANTHROPIC_API_KEY` se usa Claude para interpretar la pregunta (solo viaja el texto de la pregunta) y, sin ella o si falla, reglas locales.
- **Interfaz responsive:** verificada a 390 px (móvil), 768 px (tablet) y escritorio, sin desbordes y con controles táctiles de al menos 44 px.
- **Despliegue:** contenedor Docker listo para Hugging Face Spaces (ver `deploy/DESPLIEGUE.md`).

## Requisitos

- Python 3.10 o superior (recomendado: Python 3.11 o 3.12).
- Conexión a Internet durante la primera ejecución de PaddleOCR para descargar sus modelos preentrenados (unos 13 MB; se guardan en `~/.paddlex`, o en `PADDLE_PDX_CACHE_HOME`). Si ya los tienes descargados, apunta `PADDLE_MODELOS` a la carpeta con `PP-OCRv5_mobile_det_infer` y `latin_PP-OCRv5_mobile_rec_infer`. No se entrena ningún modelo propio.
- Los registros, las imágenes y el archivo de usuario se almacenan localmente en `data/` por defecto. Se puede cambiar con la variable de entorno `RECEIPT_DATA_DIR` (ruta absoluta o relativa al proyecto). La carpeta `data/` está excluida de Git mediante `.gitignore`.
- Streamlit 1.49 o superior (versión mínima verificada con `tests/test_ui.py`).

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

El primer procesamiento puede tardar más mientras PaddleOCR descarga los modelos. Para detener Streamlit, usa `Ctrl+C` en la terminal.

## Captura con la cámara

En la pestaña **📷 Cargar**, elige **📷 Usar cámara**: el navegador muestra la vista en vivo de la cámara y el botón *Take Photo* captura la imagen, que sigue el mismo flujo que un archivo subido (preprocesado, OCR, revisión, confirmación y guardado). La foto original se archiva como JPG.

- El navegador pide permiso para usar la cámara y solo lo concede en `localhost` o con HTTPS. Si la app se abre desde otro equipo de la red por `http://`, la cámara no estará disponible (subir archivo sí).
- Se solicita 1080p cuando la versión de Streamlit lo permite; la resolución real depende de la cámara. Para mejores resultados: boleta plana, buena iluminación, fondo oscuro y que ocupe la mayor parte del encuadre.
- El OCR tarda varios segundos por imagen, por lo que se procesa la foto capturada, no el video continuo.

## Privacidad y cifrado

| Dato | Tratamiento |
|---|---|
| Imágenes (original y procesada) | Cifradas en disco con Fernet (AES-128 + HMAC). |
| Texto OCR completo | Se enmascaran DNI, tarjetas (válidas según Luhn) y RUC `10…` de persona natural, y luego se cifra en SQLite. |
| Fecha, comercio y total | En claro: las consultas, el CSV y las preguntas los necesitan. |
| Contraseña | Solo su hash PBKDF2-HMAC-SHA256 con sal. |

La clave se toma de la variable `RECEIPT_ENCRYPTION_KEY`; si no existe, se crea `data/.secret.key` con permisos 0600. La
variable es la opción recomendada porque deja la clave fuera de la carpeta de datos. **Si se pierde la clave, los datos
cifrados no se recuperan.** Los registros anteriores al cifrado siguen leyéndose. Genera una clave con:

```bash
python -c "import crypto_service; print(crypto_service.generate_key())"
```

### Variables de entorno

| Variable | Uso |
|---|---|
| `RECEIPT_DATA_DIR` | Carpeta de datos (por defecto `data/`). |
| `RECEIPT_ENCRYPTION_KEY` | Clave de cifrado (recomendada). |
| `APP_USER` / `APP_PASSWORD` | Crean la cuenta inicial si no existe (para despliegues sin terminal). |
| `ANTHROPIC_API_KEY` | Opcional: interpreta las preguntas con Claude. |
| `NL_QUERY_MODEL` | Opcional: modelo de Claude para las preguntas (por defecto `claude-opus-5-5`). |

## Ejecución con Docker

La imagen incluye Python 3.12, PaddlePaddle (CPU), PaddleOCR con sus modelos ya descargados y la aplicación. Los datos (base SQLite, imágenes y cuenta) viven en el volumen `/data`, de modo que sobreviven a reinicios y actualizaciones de la imagen.

```bash
docker compose build
docker compose run --rm app python create_user.py   # crea la cuenta; la contraseña se escribe oculta
docker compose up -d                                 # abre http://localhost:8501
```

- `docker compose logs -f` muestra los registros y `docker compose down` detiene la app sin borrar los datos. `docker compose down -v` sí elimina el volumen con los datos.
- Copia de seguridad del volumen: `docker run --rm -v digitalizador_boletas_boletas-data:/data -v "$PWD":/backup alpine tar czf /backup/boletas.tgz -C /data .` (el prefijo del volumen depende del nombre de la carpeta del proyecto; consúltalo con `docker volume ls`).
- La imagen pesa más de 1 GB por PaddlePaddle. Argumentos de construcción opcionales:
  - `PRELOAD_MODELS=0`: no descarga los modelos al construir (se descargan en el primer uso; requiere Internet en el contenedor).
  - `BASE_IMAGE`: imagen base alternativa (por ejemplo, `public.ecr.aws/docker/library/python:3.12-slim` si Docker Hub limita las descargas).
- El contenedor usa el UID 1000. Si ya tenías un volumen creado con una versión anterior (UID 10001), corrige sus permisos con `docker compose run --rm --user root app chown -R 1000:1000 /data` o recrea el volumen.
- Para conservar los datos entre reinicios en un servidor, define `RECEIPT_ENCRYPTION_KEY` (si no, la clave se guarda en el mismo volumen).
- La autenticación es local y de demostración: si expones el puerto fuera de tu equipo, colócalo detrás de un proxy con HTTPS.

## Integración continua

`.github/workflows/ci.yml` se ejecuta en cada push y pull request:

1. **Pruebas:** `pytest` con Python 3.11 y 3.12 (PaddleOCR se omite porque las pruebas lo simulan).
2. **Imagen Docker:** construye la imagen, la arranca y comprueba `/_stcore/health`, que los módulos de la app y PaddleOCR se importan dentro del contenedor y que PaddleOCR lee una imagen de prueba.

## Estructura

```text
 digitalizador_boletas/
 ├── main.py             # Entrada de Streamlit
 ├── ui.py               # Login, carga/revisión, dashboard y evidencia (solo presentación)
 ├── receipt_service.py  # Validación, guardado de la revisión y exportación CSV
 ├── privacy.py          # Enmascarado de DNI, tarjetas y RUC de persona natural
 ├── crypto_service.py   # Cifrado en reposo de imágenes y texto OCR (Fernet)
 ├── nl_query.py         # Preguntas en lenguaje natural: reglas + Claude opcional
 ├── ocr_service.py      # OpenCV, PaddleOCR y reglas de extracción A/B
 ├── image_io.py         # Lectura de JPG, PNG y HEIC/HEIF (conversión a JPG)
 ├── repository.py       # SQLite y persistencia atómica de imágenes
 ├── auth_service.py     # PBKDF2, verificación y lectura de la cuenta
 ├── create_user.py      # Alta de cuenta local interactiva
 ├── app_config.py       # Rutas, límite de carga y carpetas
 ├── .streamlit/
 │   └── config.toml     # maxUploadSize = 10 (MB), igual que MAX_UPLOAD_BYTES
 ├── tests/
 │   ├── conftest.py             # Carpeta de datos temporal por prueba e imágenes sintéticas
 │   ├── test_ocr_service.py     # Preprocesado, inclinación, montos, fecha, comercio, total, pipeline
 │   ├── test_receipt_service.py # Validación, guardado, duplicados, limpieza y CSV
 │   ├── test_repository.py      # SQLite, filtros, rutas de imágenes
 │   ├── test_auth_service.py    # Hash, login (incluye usuarios con tildes/ñ), archivos corruptos
 │   ├── test_create_user.py     # Alta interactiva de la cuenta
 │   ├── test_app_config.py      # Rutas y límite de carga
 │   ├── test_privacy.py         # Enmascarado de datos personales
 │   ├── test_crypto_service.py  # Cifrado, claves, registros antiguos y clave perdida
 │   ├── test_nl_query.py        # Reglas, ejecución determinista y Claude simulado
 │   ├── test_paddle_reader.py   # Lector PaddleOCR (con los modelos reales si están disponibles)
 │   ├── test_extraction_improvements.py  # Fechas, comercio y total en letras
 │   ├── test_image_io.py        # Conversión de HEIC/HEIF
 │   ├── test_ui.py              # Interfaz Streamlit con AppTest (login, filtros, evidencia, preguntas)
 │   └── test_ui_capture.py      # Flujo completo archivo/cámara → OCR → revisión → guardado
 ├── experimentos/       # Evaluación del informe: datos, scripts, resultados y Experimento 2 (ver experimentos/README.md)
 ├── .github/workflows/
 │   └── ci.yml          # Pruebas + construcción y arranque de la imagen Docker
 ├── Dockerfile          # Imagen solo-CPU con modelos PaddleOCR precargados
 ├── deploy/             # Despliegue en Hugging Face Spaces (guía y script de publicación)
 ├── docker-compose.yml  # Servicio con volumen persistente para /data
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
5. **Rotación:** se rota por el mismo ángulo medido (en coordenadas de imagen un ángulo positivo es una inclinación horaria y `getRotationMatrix2D` gira en sentido antihorario con ángulos positivos), con `cv2.getRotationMatrix2D` y `cv2.warpAffine` con `cv2.INTER_CUBIC`, lienzo expandido para evitar recortes y fondo blanco (`255`).
6. **Contraste local (opcional, `enhance=True`):** `cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)`.
7. **Denoising (opcional, junto con el contraste):** `cv2.bilateralFilter(image, d=5, sigmaColor=35, sigmaSpace=35)`.
   Un recorte del papel con corrección de perspectiva también es opcional (`crop_document=True`).
   Por defecto el prototipo usa solo los pasos 1 a 5 (imagen en grises corregida en inclinación): con las boletas del proyecto fue igual o mejor que las variantes con realce o recorte.
8. **Codificación de salida:** PNG con `cv2.imencode('.png', ..., [cv2.IMWRITE_PNG_COMPRESSION, 3])`; esta copia se entrega a PaddleOCR y se conserva por separado para evidencia.

Los parámetros son un punto de partida reproducible. La comparación de las variantes con boletas reales está en `experimentos/` (`comparar_preprocesado.py`) y en el informe.

## Reglas iniciales para los formatos A y B

- **Formato A:** prioriza una etiqueta explícita (por ejemplo, `TOTAL A PAGAR`, `IMPORTE TOTAL`, `TOTAL GENERAL` o `TOTAL`). Ignora líneas etiquetadas como subtotal, IGV/IVA/impuestos, descuento, vuelto/cambio, efectivo/recibido, propina, identificadores RUC/DNI y conteos como `TOTAL ITEMS 3` o `CANT. DE ITEMS`. Si no encuentra un total etiquetado inequívoco, deja el campo vacío.
- **Formato B:** aplica primero las mismas reglas para etiquetas de total. Si no hay una etiqueta identificable, permite como alternativa un monto con moneda o decimales en el tramo final del ticket, excluyendo impuestos, subtotal, vuelto y recibido.
- **Fecha:** soporta patrones día/mes/año, día-mes-año, día.mes.año y año-mes-día; valida la fecha del calendario y favorece una etiqueta de fecha de emisión. Si dos fechas tienen puntuaciones semejantes y no hay señales suficientes para decidir, deja el campo vacío.
- **Comercio:** busca un candidato en las líneas iniciales y excluye etiquetas comunes del comprobante, identificadores y datos de contacto. Las exclusiones se comparan como palabras completas, de modo que `RUC` no descarta `TRUCK` ni `CRUCERO`. Si ninguna línea parece un comercio, deja el campo vacío.

> **Importante:** los documentos de planificación adjuntos describen dos formatos, pero no contienen imágenes de boletas ni definen el diseño exacto de A y B. Estas reglas son una base funcional, no una garantía de extracción correcta. Para cumplir de forma verificable el criterio de tres ejemplos por formato, agreguen ejemplos anonimizados y ajusten/proben las reglas con los valores de referencia del Product Owner. La revisión humana sigue siendo obligatoria.

## Base de datos y trazabilidad

SQLite conserva fecha, comercio, total en céntimos enteros, instante de registro, ubicación de la imagen original y procesada (relativa a `data/images/`, para que la base siga siendo válida si se mueve la carpeta de datos; las rutas absolutas de versiones anteriores siguen funcionando), texto completo OCR, los tres candidatos iniciales, formato utilizado e identificador único de la acción. Los valores finales se almacenan por separado de los propuestos. El campo monetario se representa en céntimos para evitar errores de punto flotante; la UI y el CSV lo muestran con dos decimales.

El CSV incluye los encabezados `id,fecha,comercio,total`, usa UTF-8 con BOM para facilitar la apertura en hojas de cálculo y exporta solo el subconjunto filtrado. Se neutralizan nombres de comercio que comiencen con caracteres de fórmula de hoja de cálculo.

## Pruebas

```bash
pytest -q
```

Las pruebas se ejecutan sobre una carpeta de datos temporal (nunca tocan `data/`) y cubren:

- **OCR:** preprocesado, corrección de inclinación con imágenes giradas sintéticamente, formatos de monto y fecha, reglas de total/comercio y el pipeline `process_receipt` completo con un lector OCR simulado y una prueba con los modelos reales de PaddleOCR.
- **Guardado:** validación de la revisión, valores propuestos vs. confirmados, idempotencia sin pérdida de evidencia y limpieza de imágenes si falla la base de datos.
- **Persistencia y autenticación:** filtros, escapes de `LIKE`, rutas de imágenes, usuarios con tildes/ñ y archivos de cuenta dañados.
- **Interfaz:** login, cierre de sesión, filtros combinados, rango invertido, evidencia y tolerancia a imágenes faltantes o dañadas, con `streamlit.testing.v1.AppTest`.

- **Captura:** flujo completo con archivo y con cámara (`AppTest` simula ambos) usando un lector OCR simulado: candidatos prellenados, corrección manual, confirmación obligatoria, guardado sin duplicados y archivo original intacto. La exactitud con boletas reales se mide en `experimentos/`, no en estas pruebas.

## Experimentos del informe final

La carpeta `experimentos/` contiene los valores de referencia de 38 boletas **reales anonimizadas** (las imágenes de 11 están en el repositorio y las de 27 se entregan aparte en el archivo de datos), los scripts que comparan PaddleOCR, RapidOCR, EasyOCR y Tesseract con el pipeline real (EasyOCR ya no es dependencia: para reproducir sus rondas, `pip install easyocr`), los resultados obtenidos y los datos del Experimento 2 (tiempo de registro con dos participantes). Las instrucciones para reproducirlos están en `experimentos/README.md`.

## Limitaciones conocidas

- Es un prototipo local, no multiusuario ni desplegado en la nube.
- El OCR depende de la calidad, iluminación, tipografía y disposición del recibo; los modelos se descargan en el primer uso.
- No valida comprobantes con SUNAT, no procesa PDF ni lotes, y no extrae líneas de productos, acorde con el alcance MVP descrito en el plan Scrum.
- La autenticación es de demostración para uso local; no sustituye un sistema de identidad para producción.
