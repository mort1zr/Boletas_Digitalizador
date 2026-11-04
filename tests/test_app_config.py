from pathlib import Path

import app_config


def test_set_data_dir_redirects_every_path(tmp_path: Path):
    app_config.set_data_dir(tmp_path / "otra")
    assert app_config.DATA_DIR == tmp_path / "otra"
    assert app_config.IMAGES_DIR == tmp_path / "otra" / "images"
    assert app_config.DATABASE_PATH == tmp_path / "otra" / "receipts.sqlite3"
    assert app_config.USERS_PATH == tmp_path / "otra" / "users.json"
    app_config.ensure_directories()
    assert app_config.IMAGES_DIR.is_dir()


def test_relative_data_dir_is_anchored_to_project():
    assert app_config._resolve_data_dir("datos") == (app_config.BASE_DIR / "datos").resolve()
    assert app_config._resolve_data_dir("") == app_config.BASE_DIR / "data"
    assert app_config._resolve_data_dir(None) == app_config.BASE_DIR / "data"


def test_upload_limit_matches_streamlit_config():
    config = (app_config.BASE_DIR / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert f"maxUploadSize = {app_config.MAX_UPLOAD_BYTES // (1024 * 1024)}" in config
