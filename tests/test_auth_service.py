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
