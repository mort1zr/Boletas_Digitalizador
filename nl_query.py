"""Consultas en lenguaje natural sobre las boletas registradas.

Diseño (ver sección 9.5 del informe): el lenguaje natural solo se traduce a un *plan de
consulta* estructurado (operación, comercio y rango de fechas). El plan lo valida este módulo y
lo ejecuta ``ReceiptRepository`` con SQL parametrizado de solo lectura; **los importes los calcula
Python con enteros (céntimos), nunca el modelo de lenguaje**, y la respuesta muestra los filtros
aplicados para que el usuario pueda verificarla. Con ello se evita que un modelo invente cifras.

Hay dos traductores del texto al plan:
* ``plan_con_reglas``: determinista, sin red ni costo; entiende las preguntas frecuentes.
* ``plan_con_claude``: usa la API de Claude (opcional, si hay ``ANTHROPIC_API_KEY``). Recibe solo
  la pregunta y la fecha de hoy; nunca los registros, las imágenes ni los nombres de comercios.
  Si falla (sin red, rechazo, respuesta inválida), se recurre a las reglas.
"""
from __future__ import annotations

import calendar
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from repository import ReceiptRepository

LOGGER = logging.getLogger(__name__)
OPERACIONES = ("total", "conteo", "promedio", "maximo", "listar")
MODELO_POR_DEFECTO = "claude-opus-5-5"
MESES = {nombre: i for i, nombre in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"], 1)}
MESES["setiembre"] = 9


class PlanConsulta(BaseModel):
    """Plan de consulta validado; es lo único que se ejecuta."""

    operacion: Literal["total", "conteo", "promedio", "maximo", "listar"] = "total"
    comercio: str | None = Field(default=None, max_length=80)
    fecha_desde: date | None = None
    fecha_hasta: date | None = None


@dataclass
class Respuesta:
    texto: str
    filtros: str
    motor: str
    filas: list[dict[str, Any]] = field(default_factory=list)
    entendida: bool = True


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_tildes.lower()).strip()


def _rango_mes(anio: int, mes: int) -> tuple[date, date]:
    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


def _mes_anterior(hoy: date) -> tuple[int, int]:
    return (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)


def _extraer_fechas(pregunta: str, hoy: date) -> tuple[date | None, date | None]:
    texto = _normalizar(pregunta)
    iso = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", texto)
    if len(iso) >= 2:
        try:
            return date.fromisoformat(iso[0]), date.fromisoformat(iso[1])
        except ValueError:
            pass
    if "mes pasado" in texto or "mes anterior" in texto:
        return _rango_mes(*_mes_anterior(hoy))
    if "este mes" in texto or "mes actual" in texto:
        return _rango_mes(hoy.year, hoy.month)
    if "ano pasado" in texto or "ano anterior" in texto:
        return date(hoy.year - 1, 1, 1), date(hoy.year - 1, 12, 31)
    if "este ano" in texto or "ano actual" in texto:
        return date(hoy.year, 1, 1), date(hoy.year, 12, 31)
    for nombre, numero in MESES.items():
        coincidencia = re.search(rf"\b{nombre}\b(?:\s+(?:de|del)\s+(\d{{4}}))?", texto)
        if coincidencia:
            if coincidencia.group(1):
                anio = int(coincidencia.group(1))
            else:
                anio = hoy.year if numero <= hoy.month else hoy.year - 1  # un mes futuro se entiende del año anterior
            return _rango_mes(anio, numero)
    anio_suelto = re.search(r"\b(?:en|de|del|durante)\s+(20\d{2})\b", texto)
    if anio_suelto:
        anio = int(anio_suelto.group(1))
        return date(anio, 1, 1), date(anio, 12, 31)
    return None, None


_PALABRAS_NO_COMERCIO = {
    "el", "la", "los", "las", "un", "una", "este", "esta", "mi", "mis", "total", "todo", "todas", "todos", "general",
    "boletas", "boleta", "compras", "gastos", "gasto", "mes", "ano", "anos", "semana", "dia", "hoy",
    "pasado", "pasada", "anterior", "actual", "ultimo", "ultimos", "de", "del",
} | set(MESES)
_CORTE_COMERCIO = re.compile(
    r"\s+(?:durante|en|del|de|este|esta|el|la|entre|desde|hasta|por|con|para|que|se|y|\d{4}-\d{2}-\d{2}|20\d{2})\b.*$"
    r"|[?!.,;:].*$", re.IGNORECASE)


def _extraer_comercio(pregunta: str) -> str | None:
    """Comercio mencionado tras «en», «a», «de» o «con» (el texto original, con sus mayúsculas)."""
    for coincidencia in re.finditer(r"\b(?:en|a|de|con)\s+([^\s?!.,;:]+(?:\s+[^\s?!.,;:]+){0,4})", pregunta, flags=re.IGNORECASE):
        candidato = _CORTE_COMERCIO.sub("", coincidencia.group(1)).strip()
        palabras = _normalizar(candidato).split()
        # Una expresión de tiempo («este mes», «el año pasado», «2026») no es un comercio.
        if not palabras or all(p in _PALABRAS_NO_COMERCIO or re.fullmatch(r"20\d{2}", p) for p in palabras):
            continue
        return candidato[:80]
    return None


def plan_con_reglas(pregunta: str, hoy: date | None = None) -> PlanConsulta | None:
    """Traduce las preguntas frecuentes; devuelve ``None`` si no reconoce una intención de consulta."""
    hoy = hoy or date.today()
    normal = _normalizar(pregunta)
    if not normal:
        return None
    if re.search(r"\b(cuantas|cuantos|numero de|cantidad de)\b.*\b(boletas|compras|comprobantes|registros)\b", normal):
        operacion = "conteo"
    elif re.search(r"\b(promedio|en promedio|media)\b", normal):
        operacion = "promedio"
    elif re.search(r"\b(mayor|mas caro|mas cara|maximo|maxima|el mas grande)\b", normal):
        operacion = "maximo"
    elif re.search(r"\b(lista|listame|muestrame|muestra|cuales|ver|mostrar|detalle)\b", normal):
        operacion = "listar"
    elif re.search(r"\b(cuanto|gaste|gastado|gasto|gastos|total|suma|sumar|pague|pagado|invertido)\b", normal):
        operacion = "total"
    else:
        return None
    desde, hasta = _extraer_fechas(pregunta, hoy)
    return PlanConsulta(operacion=operacion, comercio=_extraer_comercio(pregunta), fecha_desde=desde, fecha_hasta=hasta)


# --------------------------------------------------------------------------- Claude (opcional)
_SISTEMA = (
    "Traduces preguntas en español sobre gastos personales a un plan de consulta JSON. No respondes la pregunta ni "
    "calculas importes: solo extraes (1) la operación, (2) el comercio mencionado, exactamente como lo escribió el "
    "usuario, o null, y (3) el rango de fechas en formato AAAA-MM-DD, o null. Operaciones: total (cuánto gastó), "
    "conteo (cuántas boletas), promedio (gasto promedio), maximo (la boleta de mayor importe), listar (mostrar las "
    "boletas). Resuelve fechas relativas como «este mes» o «el mes pasado» con la fecha de hoy que se te indica; un mes "
    "nombrado sin año se refiere al año de hoy, salvo que ese mes aún no haya ocurrido (entonces es del año anterior). "
    "Si el texto no es una pregunta sobre boletas o gastos, devuelve la operación total sin comercio ni fechas."
)


def claude_disponible() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def _crear_cliente() -> Any:
    import anthropic  # import perezoso: la dependencia es opcional

    return anthropic.Anthropic(max_retries=1, timeout=30.0)


def plan_con_claude(pregunta: str, hoy: date | None = None, cliente: Any = None) -> PlanConsulta | None:
    """Pide a Claude el plan de consulta. Devuelve ``None`` ante cualquier fallo (se usarán las reglas)."""
    hoy = hoy or date.today()
    try:
        cliente = cliente or _crear_cliente()
        respuesta = cliente.beta.messages.create(
            model=os.getenv("NL_QUERY_MODEL", MODELO_POR_DEFECTO),
            max_tokens=1024,
            # Si un clasificador de seguridad rechaza la consulta, la API la reintenta con otro modelo.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=_SISTEMA,
            messages=[{"role": "user", "content": f"Fecha de hoy: {hoy.isoformat()}\nPregunta: {pregunta[:500]}"}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": {
                "type": "object", "additionalProperties": False, "required": ["operacion", "comercio", "fecha_desde", "fecha_hasta"],
                "properties": {
                    "operacion": {"type": "string", "enum": list(OPERACIONES)},
                    "comercio": {"type": ["string", "null"]},
                    "fecha_desde": {"type": ["string", "null"]},
                    "fecha_hasta": {"type": ["string", "null"]},
                }}}},
        )
        if getattr(respuesta, "stop_reason", None) == "refusal":
            LOGGER.warning("Claude rechazó la consulta; se usan las reglas.")
            return None
        texto = next((b.text for b in respuesta.content if getattr(b, "type", "") == "text"), "")
        return PlanConsulta.model_validate_json(texto)
    except (ValidationError, ValueError) as exc:
        LOGGER.warning("Respuesta de Claude no válida: %s", exc)
    except Exception as exc:  # noqa: BLE001 - red, autenticación, límites: no deben romper la interfaz
        LOGGER.warning("No se pudo consultar a Claude (%s): %s", type(exc).__name__, exc)
    return None


# --------------------------------------------------------------------------- ejecución
def _describir_filtros(plan: PlanConsulta) -> str:
    partes = []
    if plan.comercio:
        partes.append(f"comercio contiene «{plan.comercio}»")
    if plan.fecha_desde and plan.fecha_hasta:
        partes.append(f"del {plan.fecha_desde.isoformat()} al {plan.fecha_hasta.isoformat()}")
    elif plan.fecha_desde:
        partes.append(f"desde el {plan.fecha_desde.isoformat()}")
    elif plan.fecha_hasta:
        partes.append(f"hasta el {plan.fecha_hasta.isoformat()}")
    return "; ".join(partes) if partes else "sin filtros (todas las boletas)"


def _soles(centimos: int) -> str:
    return f"S/ {(Decimal(centimos) / Decimal(100)):,.2f}"


def ejecutar_plan(repositorio: ReceiptRepository, plan: PlanConsulta, motor: str) -> Respuesta:
    if plan.fecha_desde and plan.fecha_hasta and plan.fecha_desde > plan.fecha_hasta:
        plan = plan.model_copy(update={"fecha_desde": plan.fecha_hasta, "fecha_hasta": plan.fecha_desde})
    filas = repositorio.list_receipts(
        plan.fecha_desde.isoformat() if plan.fecha_desde else None,
        plan.fecha_hasta.isoformat() if plan.fecha_hasta else None,
        plan.comercio or "",
    )
    filtros = _describir_filtros(plan)
    if not filas:
        return Respuesta("No encontré boletas con esos filtros.", filtros, motor, [])
    montos = [int(f["total_cents"]) for f in filas]
    n = len(filas)
    if plan.operacion == "conteo":
        texto = f"Hay {n} boleta{'s' if n != 1 else ''} registrada{'s' if n != 1 else ''}."
    elif plan.operacion == "promedio":
        texto = f"El gasto promedio por boleta es {_soles(round(sum(montos) / n))} ({n} boletas)."
    elif plan.operacion == "maximo":
        mayor = max(filas, key=lambda f: int(f["total_cents"]))
        texto = f"La boleta de mayor importe es de {_soles(int(mayor['total_cents']))}: {mayor['merchant']}, el {mayor['receipt_date']}."
    elif plan.operacion == "listar":
        texto = f"Encontré {n} boleta{'s' if n != 1 else ''}; la suma de sus importes es {_soles(sum(montos))}."
    else:
        texto = f"El gasto total es {_soles(sum(montos))} en {n} boleta{'s' if n != 1 else ''}."
    return Respuesta(texto, filtros, motor, filas)


def responder(repositorio: ReceiptRepository, pregunta: str, hoy: date | None = None, usar_claude: bool | None = None,
              cliente: Any = None) -> Respuesta:
    """Punto de entrada: elige el traductor, ejecuta el plan y redacta la respuesta."""
    hoy = hoy or date.today()
    if not pregunta or not pregunta.strip():
        return Respuesta("Escribe una pregunta, por ejemplo: «¿Cuánto gasté en Makro en octubre?».", "—", "—", [], entendida=False)
    if usar_claude is None:
        usar_claude = claude_disponible()
    plan, motor = None, "reglas"
    if usar_claude or cliente is not None:
        plan = plan_con_claude(pregunta, hoy, cliente)
        if plan is not None:
            motor = "Claude"
    if plan is None:
        plan = plan_con_reglas(pregunta, hoy)
        motor = "reglas"
    if plan is None:
        return Respuesta(
            "No entendí la pregunta. Prueba con: «¿Cuánto gasté en Makro en octubre?», «¿Cuántas boletas tengo este mes?» "
            "o «¿Cuál fue mi compra más cara?».", "—", "reglas", [], entendida=False)
    return ejecutar_plan(repositorio, plan, motor)
