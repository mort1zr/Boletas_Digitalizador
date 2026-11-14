import pytest

from privacy import mask_personal_data


@pytest.mark.parametrize(
    ("original", "esperado"),
    [
        ("Cliente: DNI 79360747", "Cliente: DNI ********"),
        ("DNI: 12345678", "DNI: ********"),
        ("D.N.I. 12345678 gracias", "D.N.I. ******** gracias"),
        ("Nro. Doc: 12345678", "Nro. Doc: ********"),
        ("Número de Documento: 00000001", "Número de Documento: ********"),
        ("TIPODOC: DNI 0", "TIPODOC: DNI 0"),  # un solo dígito: no es un documento
        ("RUC 10756628726", "RUC 10********6"),  # persona natural: contiene el DNI del titular
        ("RUC 20608300393", "RUC 20608300393"),  # persona jurídica: dato público del comercio
        ("Tarjeta 4111 1111 1111 1111", "Tarjeta ************1111"),
        ("TC: 4111111111111111", "TC: ************1111"),
        ("4111********1111", "4111********1111"),  # ya enmascarada por el terminal
        ("ID: 0000630918177890", "ID: 0000630918177890"),  # no supera Luhn: no es tarjeta
        ("Total: S/ 126.00", "Total: S/ 126.00"),
        ("05/11/26 13:25 TICKET 20261106-05-000312340", "05/11/26 13:25 TICKET 20261106-05-000312340"),
    ],
)
def test_mask_personal_data(original, esperado):
    assert mask_personal_data(original) == esperado


def test_empty_text_is_returned_as_is():
    assert mask_personal_data("") == ""


def test_masking_is_idempotent():
    texto = "Cliente: DNI 79360747 RUC 10756628726 TC 4111111111111111"
    una_vez = mask_personal_data(texto)
    assert mask_personal_data(una_vez) == una_vez
    assert "79360747" not in una_vez and "756628726" not in una_vez and "41111111" not in una_vez


def test_masking_keeps_fields_needed_by_the_extractor():
    # La extracción de fecha, comercio y total se hace sobre el texto original; el enmascarado
    # solo se aplica al texto que se almacena y no debe tocar esas líneas.
    texto = "Fecha: 21/10/2026\nTOTAL A PAGAR S/ 118.00\nCliente: DNI 79360747"
    resultado = mask_personal_data(texto)
    assert "21/10/2026" in resultado and "118.00" in resultado
