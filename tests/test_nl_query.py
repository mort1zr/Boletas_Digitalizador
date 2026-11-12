"""Consultas en lenguaje natural: traductor de reglas, ejecución determinista y backend Claude (simulado)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import nl_query
from nl_query import PlanConsulta, plan_con_claude, plan_con_reglas, responder
from repository import ReceiptRepository

HOY = date(2026, 11, 12)


@pytest.fixture(autouse=True)
def sin_claude_por_defecto(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> ReceiptRepository:
    repo = ReceiptRepository(tmp_path / "db.sqlite3", tmp_path / "images")
    for i, (dia, comercio, centimos) in enumerate([
        ("2026-10-05", "Makro", 12000), ("2026-10-20", "MAKRO Lima", 8050), ("2026-09-30", "Makro", 5000),
        ("2026-10-11", "Tambo", 1886), ("2026-11-05", "Tambo", 1450), ("2025-10-10", "Makro", 99900)]):
        repo.save_receipt({"receipt_date": dia, "merchant": comercio, "total_cents": centimos, "image_path": "x.jpg",
                           "original_ocr_text": "", "receipt_format": "A", "source_id": f"s{i}"})
    return repo


# --- traductor de reglas -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("pregunta", "operacion", "comercio", "desde", "hasta"),
    [
        ("¿Cuánto gasté en Makro durante octubre?", "total", "Makro", date(2026, 10, 1), date(2026, 10, 31)),
        ("cuanto gaste en makro en octubre", "total", "makro", date(2026, 10, 1), date(2026, 10, 31)),
        ("¿Cuánto gasté en octubre?", "total", None, date(2026, 10, 1), date(2026, 10, 31)),
        ("¿Cuántas boletas tengo este mes?", "conteo", None, date(2026, 11, 1), date(2026, 11, 30)),
        ("¿Cuántas compras hice en Tambo?", "conteo", "Tambo", None, None),
        ("gasto promedio en Tambo el mes pasado", "promedio", "Tambo", date(2026, 10, 1), date(2026, 10, 31)),
        ("¿Cuál fue mi compra más cara este año?", "maximo", None, date(2026, 1, 1), date(2026, 12, 31)),
        ("¿Cuánto gasté en Plaza Vea en noviembre de 2025?", "total", "Plaza Vea", date(2025, 11, 1), date(2025, 11, 30)),
        ("muéstrame las boletas de Starbucks Coffee", "listar", "Starbucks Coffee", None, None),
        ("total gastado el año pasado", "total", None, date(2025, 1, 1), date(2025, 12, 31)),
        ("¿Cuánto gasté en diciembre?", "total", None, date(2025, 12, 1), date(2025, 12, 31)),  # diciembre aún no ocurrió
        ("gasto entre 2026-10-01 y 2026-10-15", "total", None, date(2026, 10, 1), date(2026, 10, 15)),
        ("¿cuánto gasté este mes?", "total", None, date(2026, 11, 1), date(2026, 11, 30)),
    ],
)
def test_rule_based_translation(pregunta, operacion, comercio, desde, hasta):
    plan = plan_con_reglas(pregunta, HOY)
    assert plan is not None
    assert (plan.operacion, plan.comercio, plan.fecha_desde, plan.fecha_hasta) == (operacion, comercio, desde, hasta)


@pytest.mark.parametrize("pregunta", ["", "   ", "hola, ¿cómo estás?", "cuéntame un chiste"])
def test_unrecognised_questions_return_none(pregunta):
    assert plan_con_reglas(pregunta, HOY) is None


# --- ejecución: las cifras las calcula el código ------------------------------------------------
def test_total_for_merchant_and_month_is_computed_by_code(repo):
    r = responder(repo, "¿Cuánto gasté en Makro durante octubre?", HOY)
    assert r.motor == "reglas" and r.entendida
    assert "S/ 200.50" in r.texto and "2 boletas" in r.texto  # 120.00 + 80.50; excluye septiembre y 2025
    assert "makro" in r.filtros.lower() and "2026-10-01" in r.filtros and "2026-10-31" in r.filtros
    assert {f["total_cents"] for f in r.filas} == {12000, 8050}


def test_count_average_max_and_list(repo):
    assert "Hay 2 boletas" in responder(repo, "¿Cuántas boletas tengo de Tambo?", HOY).texto
    assert "S/ 16.68" in responder(repo, "gasto promedio en Tambo", HOY).texto  # (18.86 + 14.50) / 2
    mayor = responder(repo, "¿Cuál fue mi compra más cara en 2026?", HOY)
    assert "S/ 120.00" in mayor.texto and "Makro" in mayor.texto
    assert "Encontré 2 boletas" in responder(repo, "muéstrame las boletas de Tambo", HOY).texto


def test_no_matches_and_not_understood(repo):
    assert "No encontré boletas" in responder(repo, "¿Cuánto gasté en Wong?", HOY).texto
    r = responder(repo, "cuéntame un chiste", HOY)
    assert r.entendida is False and "No entendí" in r.texto
    assert responder(repo, "  ", HOY).entendida is False


def test_inverted_range_is_swapped(repo):
    plan = PlanConsulta(operacion="conteo", fecha_desde=date(2026, 11, 30), fecha_hasta=date(2026, 10, 1))
    assert "Hay 4 boletas" in nl_query.ejecutar_plan(repo, plan, "reglas").texto  # oct-nov 2026 (sin sept ni 2025)


def test_like_wildcards_in_the_merchant_are_not_expanded(repo):
    plan = PlanConsulta(operacion="conteo", comercio="%")
    assert "No encontré" in nl_query.ejecutar_plan(repo, plan, "reglas").texto


# --- Claude (cliente simulado: sin red ni costo) ------------------------------------------------
class ClienteFalso:
    def __init__(self, texto: str | None = None, stop_reason: str = "end_turn", error: Exception | None = None):
        self.llamadas: list[dict] = []
        self._texto, self._stop, self._error = texto, stop_reason, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._crear))

    def _crear(self, **kwargs):
        self.llamadas.append(kwargs)
        if self._error:
            raise self._error
        bloques = [SimpleNamespace(type="text", text=self._texto)] if self._texto is not None else []
        return SimpleNamespace(content=bloques, stop_reason=self._stop)


def test_claude_plan_is_validated_and_executed_by_code(repo):
    cliente = ClienteFalso('{"operacion": "total", "comercio": "Makro", "fecha_desde": "2026-10-01", "fecha_hasta": "2026-10-31"}')
    r = responder(repo, "¿Cuánto gasté en Makro durante octubre?", HOY, cliente=cliente)
    assert r.motor == "Claude" and "S/ 200.50" in r.texto
    llamada = cliente.llamadas[0]
    assert llamada["model"] == "claude-opus-5-5" and llamada["fallbacks"] == "default"
    assert llamada["output_config"]["format"]["type"] == "json_schema"
    # Privacidad: solo viaja la pregunta y la fecha de hoy, nunca registros ni comercios guardados.
    contenido = llamada["messages"][0]["content"]
    assert "2026-11-12" in contenido and "¿Cuánto gasté en Makro durante octubre?" in contenido
    assert "Tambo" not in str(llamada) and "12000" not in str(llamada)


def test_model_can_be_changed_with_environment(repo, monkeypatch):
    monkeypatch.setenv("NL_QUERY_MODEL", "claude-haiku-5-5")
    cliente = ClienteFalso('{"operacion": "conteo", "comercio": null, "fecha_desde": null, "fecha_hasta": null}')
    plan_con_claude("¿cuántas?", HOY, cliente)
    assert cliente.llamadas[0]["model"] == "claude-haiku-5-5"


@pytest.mark.parametrize(
    "cliente",
    [
        ClienteFalso("esto no es json"),
        ClienteFalso('{"operacion": "borrar", "comercio": null, "fecha_desde": null, "fecha_hasta": null}'),
        ClienteFalso('{"operacion": "total", "comercio": null, "fecha_desde": "ayer", "fecha_hasta": null}'),
        ClienteFalso('{"operacion": "total", "comercio": "' + "x" * 200 + '", "fecha_desde": null, "fecha_hasta": null}'),
        ClienteFalso(stop_reason="refusal"),
        ClienteFalso(texto=None),
        ClienteFalso(error=RuntimeError("sin red")),
    ],
    ids=["no-json", "operacion-invalida", "fecha-invalida", "comercio-largo", "rechazo", "sin-texto", "error-de-red"],
)
def test_any_claude_failure_falls_back_to_rules_without_crashing(repo, cliente):
    r = responder(repo, "¿Cuánto gasté en Makro durante octubre?", HOY, cliente=cliente)
    assert r.motor == "reglas" and "S/ 200.50" in r.texto


def test_claude_is_used_only_when_credentials_exist(repo, monkeypatch):
    llamadas = []
    monkeypatch.setattr(nl_query, "plan_con_claude", lambda *a, **k: llamadas.append(1))
    assert responder(repo, "¿Cuántas boletas tengo?", HOY).motor == "reglas" and not llamadas
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-falsa")
    assert nl_query.claude_disponible()
    assert responder(repo, "¿Cuántas boletas tengo?", HOY).motor == "reglas" and llamadas  # intentó Claude y recurrió a reglas
