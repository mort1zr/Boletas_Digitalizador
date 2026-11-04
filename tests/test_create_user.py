import create_user
from auth_service import load_user, verify_login


def _run(monkeypatch, inputs, passwords):
    inputs, passwords = iter(inputs), iter(passwords)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr(create_user, "getpass", lambda prompt="": next(passwords))
    create_user.main()


def test_creates_account(monkeypatch, capsys):
    _run(monkeypatch, ["José"], ["Clave-Segura-2026", "Clave-Segura-2026"])
    assert "Cuenta local creada" in capsys.readouterr().out
    assert verify_login("José", "Clave-Segura-2026")


def test_mismatched_passwords_do_not_save(monkeypatch, capsys):
    _run(monkeypatch, ["operador"], ["Clave-Segura-2026", "otra-cosa-2026"])
    assert "no coinciden" in capsys.readouterr().out
    assert load_user() is None


def test_short_password_reports_error(monkeypatch, capsys):
    _run(monkeypatch, ["operador"], ["corta", "corta"])
    assert "No se pudo crear la cuenta" in capsys.readouterr().out
    assert load_user() is None


def test_existing_account_is_kept_unless_confirmed(monkeypatch, capsys):
    _run(monkeypatch, ["operador"], ["Clave-Segura-2026", "Clave-Segura-2026"])
    _run(monkeypatch, ["n"], [])
    assert "No se modificó" in capsys.readouterr().out
    _run(monkeypatch, ["s", "nuevo_usuario"], ["Otra-Clave-2026", "Otra-Clave-2026"])
    assert verify_login("nuevo_usuario", "Otra-Clave-2026")
    assert not verify_login("operador", "Clave-Segura-2026")
