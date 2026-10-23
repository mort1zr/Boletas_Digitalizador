"""Interfaz Streamlit: autenticación, digitalización, consulta y evidencia."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import streamlit as st

from app_config import MAX_UPLOAD_BYTES, USERS_PATH, ensure_directories
from auth_service import load_user, verify_login
from ocr_service import process_receipt
from repository import ReceiptRepository, RepositoryError


@st.cache_resource
def get_repository() -> ReceiptRepository:
    ensure_directories()
    return ReceiptRepository()


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
    st.caption("Prototipo local · Python · OpenCV · EasyOCR · SQLite")
    st.subheader("Iniciar sesión")
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


def _money_from_input(raw: str) -> tuple[int | None, str | None]:
    cleaned = raw.strip().replace("S/", "").replace("s/", "").replace("$", "").replace(" ", "")
    if not cleaned:
        return None, "Ingresa el total de la boleta."
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        pieces = cleaned.split(",")
        if len(pieces) == 2 and len(pieces[1]) in (1, 2):
            cleaned = pieces[0] + "." + pieces[1]
        else:
            cleaned = "".join(pieces)
    elif cleaned.count(".") > 1:
        pieces = cleaned.split(".")
        if len(pieces[-1]) in (1, 2):
            cleaned = "".join(pieces[:-1]) + "." + pieces[-1]
        else:
            cleaned = "".join(pieces)
    elif "." in cleaned:
        pieces = cleaned.split(".")
        # La moneda admite como máximo dos decimales; tres dígitos suelen ser miles.
        if len(pieces) == 2 and len(pieces[1]) == 3:
            cleaned = "".join(pieces)
    try:
        number = Decimal(cleaned).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None, "El total debe ser un número válido, por ejemplo 45.90."
    if not number.is_finite() or number <= 0:
        return None, "El total debe ser mayor que cero."
    return int(number * 100), None


def _date_from_input(raw: str) -> tuple[str | None, str | None]:
    try:
        parsed = date.fromisoformat(raw.strip())
    except (ValueError, TypeError):
        return None, "La fecha debe ser válida y usar el formato AAAA-MM-DD."
    return parsed.isoformat(), None


def _source_id_for_upload(upload_hash: str) -> str:
    if st.session_state.get("active_upload_hash") != upload_hash or not st.session_state.get("active_source_id"):
        st.session_state["active_upload_hash"] = upload_hash
        st.session_state["active_source_id"] = str(uuid.uuid4())
        st.session_state["ocr_result"] = None
        st.session_state["ocr_error"] = ""
        st.session_state["last_saved_source_id"] = ""
    return str(st.session_state["active_source_id"])


def _render_upload_tab(repository: ReceiptRepository) -> None:
    st.subheader("Digitalizar una boleta")
    st.write("Carga una sola fotografía JPG o PNG. La imagen original se conserva; el OCR usa una copia procesada.")
    uploaded = st.file_uploader("Imagen de la boleta (máximo 10 MB)", type=["jpg", "jpeg", "png"], accept_multiple_files=False, key="receipt_uploader")
    if uploaded is None:
        if st.session_state.get("active_upload_hash"):
            st.session_state["active_upload_hash"] = ""
            st.session_state["active_source_id"] = ""
            st.session_state["ocr_result"] = None
            st.session_state["ocr_error"] = ""
        st.info("Selecciona una imagen para comenzar.")
        return

    image_bytes = uploaded.getvalue()
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        st.error("El archivo supera el límite de 10 MB. Elige una imagen más pequeña.")
        return
    if not image_bytes:
        st.error("El archivo está vacío.")
        return

    # Verifica que el archivo sea realmente una imagen decodificable antes de mostrarlo.
    decoded = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None or decoded.size == 0:
        st.error("El archivo no contiene una imagen JPG/PNG válida o está dañado. Prueba con otro archivo.")
        return

    upload_hash = hashlib.sha256(image_bytes).hexdigest()
    source_id = _source_id_for_upload(upload_hash)
    left, right = st.columns([1, 1])
    with left:
        st.image(image_bytes, caption=f"Imagen original · {uploaded.name}", width="stretch")
        st.caption(f"Tamaño: {len(image_bytes) / (1024 * 1024):.2f} MB")
    with right:
        format_label = st.selectbox(
            "Distribución de la boleta",
            options=["A", "B"],
            format_func=lambda value: "Formato A · total etiquetado" if value == "A" else "Formato B · ticket / importe al final",
            key="receipt_format_choice",
            help="A prioriza etiquetas explícitas de total. B también admite un importe monetario al final cuando no hay etiqueta inequívoca. Ajusta estas reglas con las boletas reales del proyecto.",
        )
        if st.button("Procesar imagen con OpenCV + EasyOCR", type="primary", width="stretch", key="process_receipt_button"):
            try:
                with st.spinner("Corrigiendo imagen y reconociendo el texto. En el primer uso se pueden descargar los modelos de EasyOCR…"):
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
        validation_errors: list[str] = []
        normal_date, date_error = _date_from_input(date_value)
        if date_error:
            validation_errors.append(date_error)
        normal_merchant = merchant_value.strip()
        if not normal_merchant:
            validation_errors.append("El nombre del comercio no puede estar vacío.")
        total_cents, total_error = _money_from_input(total_value)
        if total_error:
            validation_errors.append(total_error)
        if not confirm:
            validation_errors.append("Marca la confirmación explícita antes de guardar.")
        if validation_errors:
            for message in validation_errors:
                st.error(message)
            return

        if st.session_state.get("last_saved_source_id") == source_id:
            st.info("Esta imagen ya se guardó desde esta sesión; no se insertó otra fila.")
            return
        original_extension = Path(uploaded.name).suffix.lower().lstrip(".") or "jpg"
        image_paths: tuple[str, str] | None = None
        try:
            image_paths = repository.persist_images(source_id, image_bytes, processed_png, original_extension)
            proposed_total, _ = _money_from_input(fields.get("total", ""))
            receipt_record = {
                "receipt_date": normal_date,
                "merchant": normal_merchant,
                "total_cents": total_cents,
                "image_path": image_paths[0],
                "processed_image_path": image_paths[1],
                "original_ocr_text": result.get("raw_text", ""),
                "proposed_date": fields.get("receipt_date", ""),
                "proposed_merchant": fields.get("merchant", ""),
                "proposed_total_cents": proposed_total,
                "receipt_format": result.get("format", format_label),
                "source_id": source_id,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            receipt_id, inserted = repository.save_receipt(receipt_record)
            if not inserted:
                repository.remove_images(*image_paths)
                st.session_state["last_saved_source_id"] = source_id
                st.success(f"La acción ya estaba registrada. ID: {receipt_id}; no se creó un duplicado.")
            else:
                st.session_state["last_saved_source_id"] = source_id
                st.session_state["selected_receipt_id"] = receipt_id
                st.success(f"Registro guardado correctamente. ID: {receipt_id}.")
                st.info("La extracción original y los valores confirmados quedaron almacenados por separado para revisar la evidencia.")
        except Exception as exc:
            if image_paths:
                repository.remove_images(*image_paths)
            st.error(f"No se pudo guardar el registro. No se confirmó una escritura exitosa. Detalle: {exc}")

    with st.expander("Ver texto original reconocido por EasyOCR"):
        st.text(result.get("raw_text", "") or "(Sin texto reconocido)")


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["id", "fecha", "comercio", "total"])
    for row in rows:
        merchant = str(row["merchant"])
        # Evita que Excel ejecute contenido del campo comercio como fórmula.
        if merchant.lstrip().startswith(("=", "+", "-", "@")):
            merchant = "'" + merchant
        total = (Decimal(int(row["total_cents"])) / Decimal(100)).quantize(Decimal("0.01"))
        writer.writerow([row["id"], row["receipt_date"], merchant, f"{total:.2f}"])
    return output.getvalue().encode("utf-8-sig")


def _format_total(cents: int | None) -> str:
    if cents is None:
        return "No detectado"
    return f"{(Decimal(int(cents)) / Decimal(100)):.2f}"


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
        image_path = Path(record["image_path"])
        if image_path.is_file():
            st.image(str(image_path), caption="Boleta original archivada", width="stretch")
        else:
            st.warning("La imagen original ya no está disponible localmente. Los datos del registro siguen accesibles.")
        processed_path_raw = record.get("processed_image_path")
        if processed_path_raw and Path(processed_path_raw).is_file():
            with st.expander("Ver imagen procesada usada por el OCR"):
                st.image(str(processed_path_raw), width="stretch")
    with details_col:
        st.markdown("**Datos propuestos originalmente por OCR**")
        proposed = st.columns(1)
        st.write(f"Fecha: {record.get('proposed_date') or 'No detectada'}")
        st.write(f"Comercio: {record.get('proposed_merchant') or 'No detectado'}")
        st.write(f"Total: {_format_total(record.get('proposed_total_cents'))}")
        st.divider()
        st.markdown("**Datos finales confirmados por el operador**")
        st.write(f"Fecha: {record['receipt_date']}")
        st.write(f"Comercio: {record['merchant']}")
        st.write(f"Total: {_format_total(record['total_cents'])}")
        st.caption(f"Formato {record['receipt_format']} · registrado {record['created_at']}")
    with st.expander("Texto íntegro reconocido por EasyOCR"):
        st.text(record.get("original_ocr_text") or "(Sin texto OCR almacenado)")


def _render_dashboard_tab(repository: ReceiptRepository) -> None:
    st.subheader("Registros guardados")
    all_rows = repository.list_receipts()
    min_iso, max_iso = repository.date_bounds()
    if min_iso and max_iso:
        default_start, default_end = date.fromisoformat(min_iso), date.fromisoformat(max_iso)
    else:
        default_start = default_end = date.today()
    first, second, third = st.columns([1, 1, 1.4])
    with first:
        start = st.date_input("Fecha desde (inclusive)", value=default_start, key="filter_start_date")
    with second:
        end = st.date_input("Fecha hasta (inclusive)", value=default_end, key="filter_end_date")
    with third:
        merchant_query = st.text_input("Comercio contiene", value="", key="filter_merchant")
    if start > end:
        st.error("El rango de fechas está invertido: la fecha inicial debe ser anterior o igual a la final.")
        rows: list[dict[str, Any]] = []
    else:
        rows = repository.list_receipts(start.isoformat(), end.isoformat(), merchant_query)

    st.caption(f"{len(rows)} registro(s) · ordenados por fecha de boleta descendente")
    visible = [
        {"ID": row["id"], "Fecha": row["receipt_date"], "Comercio": row["merchant"], "Total": _format_total(row["total_cents"])}
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
            key="receipts_table",
        )
        selected_rows = frame.selection.rows if hasattr(frame, "selection") else []
        if selected_rows:
            selected_index = selected_rows[0]
            if 0 <= selected_index < len(rows):
                selected_id = int(rows[selected_index]["id"])
                st.session_state["selected_receipt_id"] = selected_id
        selected_for_evidence = selected_id
        csv_content = _csv_bytes(rows)
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


def render_app() -> None:
    st.set_page_config(page_title="Digitalizador de boletas", page_icon="🧾", layout="wide")
    _initialise_state()
    if not st.session_state["authenticated"]:
        _login_screen()
        return

    repository = get_repository()
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
    upload_tab, dashboard_tab = st.tabs(["📷 Cargar y revisar", "📊 Consultar registros"])
    with upload_tab:
        _render_upload_tab(repository)
    with dashboard_tab:
        _render_dashboard_tab(repository)
