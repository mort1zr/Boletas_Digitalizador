import json
from pathlib import Path

from auth_service import verify_login, write_user


def test_password_is_not_stored_in_plain_text(tmp_path: Path):
    user_file = tmp_path / "users.json"
    password = "Local-Password-2026!"
    write_user("operador", password, user_file)
    content = user_file.read_text(encoding="utf-8")
    record = json.loads(content)
    assert password not in content
    assert record["password_hash"] != password
    assert verify_login("operador", password, user_file)
    assert not verify_login("operador", "wrong-password", user_file)
    assert not verify_login("otra-cuenta", password, user_file)


import pytest  # noqa: E402

import app_config  # noqa: E402
from auth_service import load_user  # noqa: E402


@pytest.mark.parametrize("username", ["José", "Muñoz", "operador_ñ", "Zoë"])
def test_non_ascii_usernames_can_log_in(tmp_path: Path, username: str):
    user_file = tmp_path / "users.json"
    write_user(username, "Local-Password-2026!", user_file)
    assert verify_login(username, "Local-Password-2026!", user_file)
    assert not verify_login(username, "otra-clave-larga", user_file)


def test_non_ascii_attempt_against_ascii_user_does_not_crash(tmp_path: Path):
    user_file = tmp_path / "users.json"
    write_user("operador", "Local-Password-2026!", user_file)
    assert not verify_login("operadór", "Local-Password-2026!", user_file)


def test_username_unicode_normalisation_and_whitespace(tmp_path: Path):
    user_file = tmp_path / "users.json"
    write_user("José", "Local-Password-2026!", user_file)  # tilde combinada
    assert verify_login("  José  ", "Local-Password-2026!", user_file)  # tilde precompuesta


@pytest.mark.parametrize(("username", "password"), [("ab", "Local-Password-2026!"), ("operador", "corta"), ("   ", "Local-Password-2026!")])
def test_invalid_accounts_are_rejected(tmp_path: Path, username: str, password: str):
    with pytest.raises(ValueError):
        write_user(username, password, tmp_path / "users.json")
    assert not (tmp_path / "users.json").exists()


def test_empty_password_never_logs_in(tmp_path: Path):
    user_file = tmp_path / "users.json"
    write_user("operador", "Local-Password-2026!", user_file)
    assert not verify_login("operador", "", user_file)


@pytest.mark.parametrize(
    "content",
    ["{no es json", "[]", json.dumps({"username": "x"}), json.dumps({
        "username": "x", "salt": "00", "password_hash": "00", "iterations": 1, "algorithm": "md5"})],
)
def test_corrupt_or_unknown_user_files_are_ignored(tmp_path: Path, content: str):
    user_file = tmp_path / "users.json"
    user_file.write_text(content, encoding="utf-8")
    assert load_user(user_file) is None
    assert not verify_login("x", "cualquier-clave", user_file)


def test_bad_salt_does_not_crash(tmp_path: Path):
    user_file = tmp_path / "users.json"
    user_file.write_text(json.dumps({
        "username": "operador", "salt": "zz", "password_hash": "00", "iterations": 1000,
        "algorithm": "pbkdf2_hmac_sha256"}), encoding="utf-8")
    assert not verify_login("operador", "Local-Password-2026!", user_file)


def test_default_path_follows_configured_data_dir():
    write_user("operador", "Local-Password-2026!")
    assert app_config.USERS_PATH.is_file()
    assert verify_login("operador", "Local-Password-2026!")
