"""Interfaz Streamlit: autenticación, digitalización, consulta y evidencia."""
from __future__ import annotations

import hashlib
import inspect
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

import cv2
import numpy as np
import streamlit as st

import app_config
import crypto_service
import image_io
import nl_query
import auth_service
from auth_service import load_user, verify_login
from ocr_service import process_receipt
from receipt_service import csv_bytes, format_total, save_reviewed_receipt, validate_review
from repository import ReceiptRepository


@st.cache_resource
def get_repository(database_path: str, images_dir: str) -> ReceiptRepository:
    # Las rutas forman parte de la clave de caché: si cambia la carpeta de datos,
    # se crea un repositorio nuevo en lugar de reutilizar uno apuntando a otra ruta.
    app_config.ensure_directories()
    return ReceiptRepository(database_path, images_dir)


def _repository() -> ReceiptRepository:
    return get_repository(str(app_config.DATABASE_PATH), str(app_config.IMAGES_DIR))


# Ajustes para pantallas pequeñas. Streamlit ya apila las columnas en móvil; aquí se reducen los
# márgenes y el título, se agrandan los controles táctiles (≥ 44 px, guía WCAG 2.5.5) y se
# evita que tablas e imágenes ensanchen la página.
_CSS_RESPONSIVE = """
<style>
html, body { overflow-x: hidden; }
[data-testid="stImage"] img, [data-testid="stCameraInput"] video { max-width: 100%; height: auto; }
[data-testid="stCameraInput"] video { border-radius: .5rem; }
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button { min-height: 2.75rem; }
@media (max-width: 640px) {
  .block-container { padding: 1rem .75rem 4rem !important; }
  h1 { font-size: 1.55rem !important; line-height: 1.2 !important; padding-bottom: .25rem !important; }
  h2, h3, h4 { font-size: 1.2rem !important; line-height: 1.3 !important; }
  [data-testid="stTabs"] [role="tab"] { padding: .6rem .7rem; min-height: 2.75rem; }
  [data-testid="stRadio"] label { min-height: 2.5rem; align-items: center; }
  [data-baseweb="input"] input, [data-baseweb="select"] > div { min-height: 2.75rem; font-size: 1rem; }
  [data-testid="stFileUploaderDropzone"] { padding: .75rem; }
  [data-testid="stDataFrame"] { max-width: 100%; }
  [data-testid="stCaptionContainer"] { font-size: .85rem; }
}
</style>
"""


def _initialise_state() -> None:
    defaults = {
        "authenticated": False,
        "username": "",
        "active_upload_hash": "",
        "active_source_id": "",
        "ocr_result": None,
        "ocr_error": "",
        "selected_receipt_id": None,
        "last_saved_source_id": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _clear_work_state() -> None:
    preserve = {"authenticated", "username"}
    for key in list(st.session_state.keys()):
        if key not in preserve:
            del st.session_state[key]
    st.session_state["active_upload_hash"] = ""
    st.session_state["active_source_id"] = ""
    st.session_state["ocr_result"] = None
    st.session_state["ocr_error"] = ""
    st.session_state["selected_receipt_id"] = None
    st.session_state["last_saved_source_id"] = ""


def _login_screen() -> None:
    st.title("Digitalizador inteligente de boletas")
    st.caption("Prototipo local · Python · OpenCV · PaddleOCR · SQLite")
    st.subheader("Iniciar sesión")
    try:
        auth_service.bootstrap_user_from_env()
    except ValueError as exc:
        st.error(f"La cuenta definida en APP_USER/APP_PASSWORD no es válida: {exc}")
    if load_user() is None:
        st.warning("Todavía no existe una cuenta local. Cierra esta app y ejecuta `python create_user.py` en la terminal del proyecto.")
        st.code("python create_user.py\nstreamlit run main.py", language="powershell")
        return
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Usuario", autocomplete="username")
        password = st.text_input("Contraseña", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Entrar", type="primary", width="stretch")
    if submitted:
        if verify_login(username, password):
            st.session_state["authenticated"] = True
            st.session_state["username"] = username.strip()
            st.session_state["ocr_result"] = None
            st.session_state["ocr_error"] = ""
            st.rerun()
        else:
            st.error("No se pudo iniciar sesión. Comprueba las credenciales.")


def _source_id_for_upload(upload_hash: str) -> str:
    if st.session_state.get("active_upload_hash") != upload_hash or not st.session_state.get("active_source_id"):
        st.session_state["active_upload_hash"] = upload_hash
        st.session_state["active_source_id"] = str(uuid.uuid4())
        st.session_state["ocr_result"] = None
        st.session_state["ocr_error"] = ""
        st.session_state["last_saved_source_id"] = ""
    return str(st.session_state["active_source_id"])


SOURCE_FILE = "📁 Subir archivo"
SOURCE_CAMERA = "📷 Usar cámara"


@dataclass(frozen=True)
class SelectedImage:
    content: bytes
    filename: str  # determina la extensión con la que se archiva el original
    label: str  # texto que se muestra bajo la vista previa


def _camera_options() -> dict[str, Any]:
    # 'resolution' solo existe en versiones recientes de Streamlit; se pide 1080p
    # cuando está disponible porque el OCR necesita el mayor detalle posible.
    if "resolution" in inspect.signature(st.camera_input).parameters:
        return {"resolution": "1080p"}
    return {}


def _select_image() -> SelectedImage | None:
    """Obtiene la imagen desde un archivo o desde la cámara del navegador."""
    source = st.radio(
        "Origen de la imagen",
        options=[SOURCE_FILE, SOURCE_CAMERA],
        horizontal=True,
        key="image_source",
    )
    if source == SOURCE_CAMERA:
        st.caption(
            "Coloca la boleta plana, con buena luz y ocupando la mayor parte del encuadre; "
            "un fondo oscuro ayuda. El navegador pedirá permiso para usar la cámara "
            "(solo funciona en localhost o con HTTPS)."
        )
        photo = st.camera_input("Toma una foto de la boleta", key="receipt_camera", **_camera_options())
        if photo is None:
            return None
        return SelectedImage(photo.getvalue(), "camara.jpg", "Foto tomada con la cámara")
    uploaded = st.file_uploader(
        "Foto de la boleta (máximo 10 MB)", type=["jpg", "jpeg", "png", "heic", "heif"],
        accept_multiple_files=False, key="receipt_uploader",
    )
    if uploaded is None:
        return None
    content = uploaded.getvalue()
    if len(content) > app_config.MAX_UPLOAD_BYTES:
        return SelectedImage(content, uploaded.name, uploaded.name)  # el aviso de tamaño lo da quien llama
    try:
        content, name = image_io.to_supported_image(content, uploaded.name)
    except ValueError as exc:
        st.error(str(exc))
        return None
    label = uploaded.name if name == uploaded.name else f"{uploaded.name} (convertida a JPG)"
    return SelectedImage(content, name, label)


def _render_upload_tab(repository: ReceiptRepository) -> None:
    st.subheader("Digitalizar una boleta")
    st.write(
        "Sube la foto tal como la toma tu celular (JPG, PNG o HEIC de iPhone y Samsung), o tómala con la cámara. "
        "La imagen original se conserva; el OCR usa una copia procesada."
    )
    selected = _select_image()
    if selected is None:
        if st.session_state.get("active_upload_hash"):
            st.session_state["active_upload_hash"] = ""
            st.session_state["active_source_id"] = ""
            st.session_state["ocr_result"] = None
            st.session_state["ocr_error"] = ""
        st.info("Selecciona una imagen o toma una foto para comenzar.")
        return

    image_bytes = selected.content
    if len(image_bytes) > app_config.MAX_UPLOAD_BYTES:
        st.error("El archivo supera el límite de 10 MB. Elige una imagen más pequeña.")
        return
    if not image_bytes:
        st.error("El archivo está vacío.")
        return

    # Verifica que el archivo sea realmente una imagen decodificable antes de mostrarlo.
    decoded = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None or decoded.size == 0:
        st.error("El archivo no contiene una imagen válida o está dañado. Prueba con otro archivo.")
        return

    upload_hash = hashlib.sha256(image_bytes).hexdigest()
    source_id = _source_id_for_upload(upload_hash)
    left, right = st.columns([1, 1])
    with left:
        st.image(image_bytes, caption=f"Imagen original · {selected.label}", width="stretch")
        st.caption(f"Tamaño: {len(image_bytes) / (1024 * 1024):.2f} MB")
    with right:
        format_label = st.selectbox(
            "Distribución de la boleta",
            options=["A", "B"],
            format_func=lambda value: "Formato A · total etiquetado" if value == "A" else "Formato B · ticket / importe al final",
            key="receipt_format_choice",
            help="A prioriza etiquetas explícitas de total. B también admite un importe monetario al final cuando no hay etiqueta inequívoca. Ajusta estas reglas con las boletas reales del proyecto.",
        )
        if st.button("Procesar imagen con OpenCV + PaddleOCR", type="primary", width="stretch", key="process_receipt_button"):
            try:
                with st.spinner("Corrigiendo imagen y reconociendo el texto. En el primer uso se pueden descargar los modelos de PaddleOCR…"):
                    result = process_receipt(image_bytes, format_label)
                    # La sesión guarda el resultado para que los reruns no vuelvan a ejecutar el OCR.
                    result["format"] = format_label
                    result["upload_sha256"] = upload_hash
                    st.session_state["ocr_result"] = result
                    st.session_state["ocr_error"] = ""
            except Exception as exc:  # La interfaz comunica el error sin interrumpir el proceso.
                st.session_state["ocr_result"] = None
                st.session_state["ocr_error"] = str(exc)
        if st.session_state.get("ocr_error"):
            st.error(st.session_state["ocr_error"])

    result = st.session_state.get("ocr_result")
    if not result or result.get("upload_sha256") != upload_hash:
        return
    if result.get("format") != format_label:
        st.warning("Cambiaste el formato de la boleta. Vuelve a ejecutar el procesamiento para aplicar las reglas correspondientes.")
        return

    processed_png = result["processed_png"]
    col_original, col_processed = st.columns(2)
    with col_original:
        st.image(image_bytes, caption="Original (sin modificar)", width="stretch")
    with col_processed:
        st.image(processed_png, caption=f"Procesada para OCR · rotación estimada {result['rotation_degrees']:.2f}°", width="stretch")
    if result.get("fields", {}).get("warnings"):
        for warning in result["fields"]["warnings"]:
            st.warning(warning)

    fields = result["fields"]
    st.markdown("#### Revisa los campos antes de confirmar")
    st.caption("Los candidatos OCR pueden ser incorrectos. El registro solo se guarda después de validar y marcar la confirmación explícita.")
    with st.form("receipt_review_form", clear_on_submit=False):
        date_value = st.text_input(
            "Fecha (AAAA-MM-DD)", value=fields.get("receipt_date", ""),
            help="Se valida como fecha de calendario antes de guardar.", key=f"review_date_{source_id}"
        )
        merchant_value = st.text_input(
            "Comercio", value=fields.get("merchant", ""), key=f"review_merchant_{source_id}"
        )
        total_value = st.text_input(
            "Total", value=fields.get("total", ""),
            help="Importe positivo; admite punto o coma decimal.", key=f"review_total_{source_id}"
        )
        confirm = st.checkbox(
            "Confirmo que revisé la imagen y que estos datos son correctos.",
            value=False, key=f"review_confirm_{source_id}"
        )
        save_clicked = st.form_submit_button("Guardar registro confirmado", type="primary", width="stretch")
    if save_clicked:
        reviewed, validation_errors = validate_review(date_value, merchant_value, total_value, confirm)
        if reviewed is None:
            for message in validation_errors:
                st.error(message)
            return
        if st.session_state.get("last_saved_source_id") == source_id:
            st.info("Esta imagen ya se guardó desde esta sesión; no se insertó otra fila.")
            return
        try:
            outcome = save_reviewed_receipt(
                repository,
                source_id=source_id,
                image_bytes=image_bytes,
                original_filename=selected.filename,
                ocr_result=result,
                reviewed=reviewed,
                receipt_format=result.get("format", format_label),
            )
        except Exception as exc:
            st.error(f"No se pudo guardar el registro. No se confirmó una escritura exitosa. Detalle: {exc}")
        else:
            st.session_state["last_saved_source_id"] = source_id
            if outcome.inserted:
                st.session_state["selected_receipt_id"] = outcome.receipt_id
                st.success(f"Registro guardado correctamente. ID: {outcome.receipt_id}.")
                st.info("La extracción original y los valores confirmados quedaron almacenados por separado para revisar la evidencia.")
            else:
                st.success(f"La acción ya estaba registrada. ID: {outcome.receipt_id}; no se creó un duplicado.")

    with st.expander("Ver texto original reconocido por PaddleOCR"):
        st.text(result.get("raw_text", "") or "(Sin texto reconocido)")


def _show_archived_image(repository: ReceiptRepository, stored: str | None, **kwargs: Any) -> bool:
    """Muestra una imagen archivada (descifrándola); si falta o está dañada, avisa sin romper la página."""
    try:
        contenido = repository.read_image(stored)
    except crypto_service.DecryptionError as exc:
        st.warning(f"No se pudo abrir la imagen archivada: {exc}")
        return True
    if contenido is None:
        return False
    try:
        st.image(contenido, **kwargs)
    except Exception:
        st.warning("No se pudo abrir la imagen archivada; puede estar dañada.")
    return True


def _render_evidence(repository: ReceiptRepository, selected_id: int | None) -> None:
    if selected_id is None:
        st.caption("Selecciona una fila de la tabla para revisar su evidencia OCR.")
        return
    record = repository.get_receipt(int(selected_id))
    if record is None:
        st.warning("No se encontró el registro seleccionado.")
        return
    st.markdown(f"#### Evidencia del registro ID {record['id']}")
    image_col, details_col = st.columns([1, 1])
    with image_col:
        if not _show_archived_image(repository, record["image_path"], caption="Boleta original archivada", width="stretch"):
            st.warning("La imagen original ya no está disponible localmente. Los datos del registro siguen accesibles.")
        procesada = repository.resolve_image_path(record.get("processed_image_path"))
        if procesada is not None and procesada.is_file():
            with st.expander("Ver imagen procesada usada por el OCR"):
                _show_archived_image(repository, record.get("processed_image_path"), width="stretch")
    with details_col:
        st.markdown("**Datos propuestos originalmente por OCR**")
        st.write(f"Fecha: {record.get('proposed_date') or 'No detectada'}")
        st.write(f"Comercio: {record.get('proposed_merchant') or 'No detectado'}")
        st.write(f"Total: {format_total(record.get('proposed_total_cents'))}")
        st.divider()
        st.markdown("**Datos finales confirmados por el operador**")
        st.write(f"Fecha: {record['receipt_date']}")
        st.write(f"Comercio: {record['merchant']}")
        st.write(f"Total: {format_total(record['total_cents'])}")
        st.caption(f"Formato {record['receipt_format']} · registrado {record['created_at']}")
    with st.expander("Texto reconocido por PaddleOCR (datos personales enmascarados)"):
        if record.get("ocr_error"):
            st.warning(record["ocr_error"])
        else:
            st.text(record.get("original_ocr_text") or "(Sin texto OCR almacenado)")


def _render_dashboard_tab(repository: ReceiptRepository) -> None:
    st.subheader("Registros guardados")
    min_iso, max_iso = repository.date_bounds()
    first, second, third = st.columns([1, 1, 1.4])
    # Los filtros de fecha empiezan vacíos (sin límite). Un rango por defecto
    # min..max quedaría congelado en la sesión y ocultaría registros nuevos.
    with first:
        start = st.date_input(
            "Fecha desde (inclusive)", value=None, key="filter_start_date",
            help="Déjalo vacío para no limitar la fecha inicial.",
            min_value=date(1900, 1, 1), max_value=date(2100, 12, 31),
        )
    with second:
        end = st.date_input(
            "Fecha hasta (inclusive)", value=None, key="filter_end_date",
            help="Déjalo vacío para no limitar la fecha final.",
            min_value=date(1900, 1, 1), max_value=date(2100, 12, 31),
        )
    with third:
        merchant_query = st.text_input("Comercio contiene", value="", key="filter_merchant")
    if min_iso and max_iso:
        st.caption(f"Rango de fechas registrado: {min_iso} a {max_iso}")
    if start is not None and end is not None and start > end:
        st.error("El rango de fechas está invertido: la fecha inicial debe ser anterior o igual a la final.")
        rows: list[dict[str, Any]] = []
    else:
        rows = repository.list_receipts(
            start.isoformat() if start else None,
            end.isoformat() if end else None,
            merchant_query,
        )

    st.caption(f"{len(rows)} registro(s) · ordenados por fecha de boleta descendente")
    visible = [
        {"ID": row["id"], "Fecha": row["receipt_date"], "Comercio": row["merchant"], "Total": format_total(row["total_cents"])}
        for row in rows
    ]
    if not rows:
        st.info("No hay registros para los filtros seleccionados.")
    else:
        selected_id = st.session_state.get("selected_receipt_id")
        matching_ids = [row["id"] for row in rows]
        if selected_id not in matching_ids:
            selected_id = None
        frame = st.dataframe(
            visible,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            # La selección es un índice posicional: si cambian los filtros, la clave
            # cambia y la selección se reinicia en vez de apuntar a otra fila.
            key=f"receipts_table_{start}_{end}_{merchant_query.strip().lower()}",
        )
        selected_rows = frame.selection.rows if hasattr(frame, "selection") else []
        if selected_rows:
            selected_index = selected_rows[0]
            if 0 <= selected_index < len(rows):
                selected_id = int(rows[selected_index]["id"])
                st.session_state["selected_receipt_id"] = selected_id
        selected_for_evidence = selected_id
        csv_content = csv_bytes(rows)
        st.download_button(
            "Exportar filas filtradas a CSV",
            data=csv_content,
            file_name=f"boletas_{date.today().isoformat()}.csv",
            mime="text/csv; charset=utf-8",
            disabled=not rows,
            width="content",
        )
        st.caption("El CSV contiene exactamente las filas filtradas y conserva el total con dos decimales.")
        st.divider()
        _render_evidence(repository, selected_for_evidence)


def _render_ask_tab(repository: ReceiptRepository) -> None:
    st.subheader("Pregunta sobre tus gastos")
    claude = nl_query.claude_disponible()
    st.caption(
        "Escribe una pregunta en español, por ejemplo: «¿Cuánto gasté en Makro durante octubre?», "
        "«¿Cuántas boletas tengo este mes?» o «¿Cuál fue mi compra más cara?». "
        + ("La pregunta se interpreta con Claude y, si no responde, con reglas; nunca se envían tus boletas, solo el texto de la pregunta."
           if claude else "La pregunta se interpreta con reglas locales; no se envía nada a Internet.")
    )
    with st.form("ask_form", clear_on_submit=False):
        pregunta = st.text_input("Tu pregunta", key="ask_question", placeholder="¿Cuánto gasté en Makro durante octubre?")
        enviada = st.form_submit_button("Preguntar", type="primary", width="stretch")
    if not enviada:
        return
    respuesta = nl_query.responder(repository, pregunta)
    if not respuesta.entendida:
        st.info(respuesta.texto)
        return
    st.success(respuesta.texto)
    st.caption(f"Filtros aplicados: {respuesta.filtros} · Motor: {respuesta.motor} · "
               "Las cifras se calculan con tus registros, no las genera el modelo.")
    if respuesta.filas:
        with st.expander(f"Ver las {len(respuesta.filas)} boleta(s) consideradas"):
            st.dataframe(
                [{"ID": f["id"], "Fecha": f["receipt_date"], "Comercio": f["merchant"], "Total": format_total(f["total_cents"])}
                 for f in respuesta.filas],
                width="stretch", hide_index=True,
            )


def render_app() -> None:
    st.set_page_config(page_title="Digitalizador de boletas", page_icon="🧾", layout="wide", initial_sidebar_state="collapsed")
    st.markdown(_CSS_RESPONSIVE, unsafe_allow_html=True)
    _initialise_state()
    if not st.session_state["authenticated"]:
        _login_screen()
        return

    repository = _repository()
    st.title("Digitalizador inteligente de boletas")
    st.caption(f"Sesión local: {st.session_state['username']} · los datos se conservan en SQLite local")
    with st.sidebar:
        st.markdown("### Navegación")
        st.write(f"Usuario: **{st.session_state['username']}**")
        if st.button("Cerrar sesión", width="stretch"):
            _clear_work_state()
            st.session_state["authenticated"] = False
            st.session_state["username"] = ""
            st.rerun()
        st.divider()
        st.caption("OCR asistido: revisa los campos y confirma antes de guardar.")
    upload_tab, dashboard_tab, ask_tab = st.tabs(["📷 Cargar", "📊 Registros", "💬 Preguntar"])
    with upload_tab:
        _render_upload_tab(repository)
    with dashboard_tab:
        _render_dashboard_tab(repository)
    with ask_tab:
        _render_ask_tab(repository)
