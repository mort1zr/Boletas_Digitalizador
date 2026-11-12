"""Enmascarado de datos personales en el texto OCR antes de almacenarlo.

Un comprobante puede imprimir el DNI del comprador, el número de una tarjeta o un RUC de
persona natural (que empieza en 10 e incluye el DNI del titular). Guardarlos en la base de
datos no aporta nada al registro (fecha, comercio y total) y aumenta el daño si se filtran,
así que se minimizan antes de persistir (principio de minimización de la Ley N.° 29733).
"""
from __future__ import annotations

import re

# «DNI 12345678», «Cliente: DNI 12345678», «Nro. Doc: 12345678», «Número de Documento: 00000001».
_DOCUMENTO_RE = re.compile(
    r"(?i)(\b(?:D\.?N\.?I\.?|C\.?E\.?|Doc(?:umento)?|Nro\.?\s*Doc(?:umento)?|N[°º]\s*Doc(?:umento)?)\b[^\d\n]{0,24}?)(\d{8})(?!\d)"
)
# RUC de persona natural: 11 dígitos que empiezan en 10 (contienen el DNI del titular).
_RUC_PERSONA_RE = re.compile(r"(?<!\d)(10)(\d{8})(\d)(?!\d)")
# Posible número de tarjeta: 13 a 19 dígitos con espacios o guiones opcionales.
_TARJETA_RE = re.compile(r"(?<![\d*])(?:\d[ -]?){12,18}\d(?![\d*])")

MARCA = "*"


def _luhn_valido(digitos: str) -> bool:
    total, alternar = 0, False
    for caracter in reversed(digitos):
        valor = int(caracter)
        if alternar:
            valor *= 2
            if valor > 9:
                valor -= 9
        total += valor
        alternar = not alternar
    return total % 10 == 0


def _enmascarar_tarjeta(coincidencia: re.Match[str]) -> str:
    texto = coincidencia.group(0)
    digitos = re.sub(r"\D", "", texto)
    if not 13 <= len(digitos) <= 19 or not _luhn_valido(digitos):
        return texto  # no es una tarjeta (p. ej., un código de operación): se deja igual
    return MARCA * (len(digitos) - 4) + digitos[-4:]


def mask_personal_data(texto: str) -> str:
    """Devuelve el texto con DNI, RUC de persona natural y números de tarjeta enmascarados."""
    if not texto:
        return texto
    resultado = _DOCUMENTO_RE.sub(lambda m: m.group(1) + MARCA * 8, texto)
    resultado = _RUC_PERSONA_RE.sub(lambda m: m.group(1) + MARCA * 8 + m.group(3), resultado)
    return _TARJETA_RE.sub(_enmascarar_tarjeta, resultado)
