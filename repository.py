"""Persistencia SQLite e imágenes locales para las boletas confirmadas."""
from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import app_config


class RepositoryError(RuntimeError):
    """Error controlado de persistencia."""


class DuplicateSubmission(RepositoryError):
    """La misma acción de guardado ya se insertó previamente."""


class ReceiptRepository:
    def __init__(self, database_path: Path | None = None, images_dir: Path | None = None) -> None:
        # Los valores por defecto se leen al construir, no al importar el módulo.
        self.database_path = Path(database_path if database_path is not None else app_config.DATABASE_PATH)
        self.images_dir = Path(images_dir if images_dir is not None else app_config.IMAGES_DIR)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            # El context manager nativo administra commit/rollback; finally garantiza el cierre.
            with connection:
                yield connection
        finally:
            connection.close()

    def init_db(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS receipts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_date TEXT NOT NULL,
                    merchant TEXT NOT NULL,
                    total_cents INTEGER NOT NULL CHECK (total_cents > 0),
                    created_at TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    processed_image_path TEXT,
                    original_ocr_text TEXT NOT NULL,
                    proposed_date TEXT,
                    proposed_merchant TEXT,
                    proposed_total_cents INTEGER,
                    receipt_format TEXT NOT NULL CHECK (receipt_format IN ('A', 'B')),
                    source_id TEXT NOT NULL UNIQUE
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(receipt_date DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_receipts_merchant ON receipts(merchant COLLATE NOCASE)")

    def persist_images(self, source_id: str, original_bytes: bytes, processed_png: bytes, original_extension: str) -> tuple[str, str]:
        """Escribe ambas evidencias usando nombres generados por la aplicación.

        Devuelve rutas relativas a la carpeta de imágenes para que la base de
        datos siga siendo válida si se mueve la carpeta de datos (o se monta en
        otra ruta dentro de un contenedor).
        """
        safe_id = re_safe_id(source_id)
        extension = original_extension.lower().lstrip(".")
        if extension not in {"jpg", "jpeg", "png"}:
            extension = "jpg"
        original_path = self.images_dir / f"{safe_id}_original.{extension}"
        processed_path = self.images_dir / f"{safe_id}_processed.png"
        self._atomic_write(original_path, original_bytes)
        try:
            self._atomic_write(processed_path, processed_png)
        except Exception:
            original_path.unlink(missing_ok=True)
            raise
        return original_path.name, processed_path.name

    def resolve_image_path(self, stored: str | None) -> Path | None:
        """Convierte la ruta guardada en una ruta utilizable.

        Acepta el formato actual (nombre relativo a ``images_dir``) y el formato
        heredado (ruta absoluta). Las rutas relativas que intenten salir de la
        carpeta de imágenes se rechazan.
        """
        if not stored:
            return None
        candidate = Path(stored)
        if candidate.is_absolute():
            return candidate
        images_root = self.images_dir.resolve()
        resolved = (images_root / candidate).resolve()
        if not resolved.is_relative_to(images_root):
            return None
        return resolved

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def remove_images(self, *paths: str | None) -> None:
        for value in paths:
            if not value:
                continue
            try:
                path = self.resolve_image_path(value)
                # Solo eliminar ficheros contenidos en la carpeta de imágenes configurada.
                if path is not None and path.resolve().is_relative_to(self.images_dir.resolve()):
                    path.unlink(missing_ok=True)
            except (OSError, ValueError):
                continue

    def save_receipt(self, record: dict[str, Any]) -> tuple[int, bool]:
        """Devuelve (id, inserted); una repetición del mismo source_id no crea otra fila."""
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO receipts (
                        receipt_date, merchant, total_cents, created_at, image_path,
                        processed_image_path, original_ocr_text, proposed_date,
                        proposed_merchant, proposed_total_cents, receipt_format, source_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["receipt_date"], record["merchant"], int(record["total_cents"]),
                        record.get("created_at") or datetime.now().astimezone().isoformat(timespec="seconds"),
                        record["image_path"], record.get("processed_image_path"),
                        record.get("original_ocr_text", ""), record.get("proposed_date") or None,
                        record.get("proposed_merchant") or None,
                        int(record["proposed_total_cents"]) if record.get("proposed_total_cents") is not None else None,
                        record["receipt_format"], record["source_id"],
                    ),
                )
                inserted = cursor.rowcount == 1
                if inserted:
                    return int(cursor.lastrowid), True
                existing = connection.execute("SELECT id FROM receipts WHERE source_id = ?", (record["source_id"],)).fetchone()
                if existing:
                    return int(existing["id"]), False
                raise RepositoryError("No se pudo insertar el registro por una restricción de base de datos.")
        except sqlite3.Error as exc:
            raise RepositoryError(f"SQLite no pudo guardar el registro: {exc}") from exc

    def find_by_source_id(self, source_id: str) -> int | None:
        with self._connect() as connection:
            row = connection.execute("SELECT id FROM receipts WHERE source_id = ?", (source_id,)).fetchone()
        return int(row["id"]) if row else None

    def list_receipts(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        merchant_query: str = "",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if start_date:
            clauses.append("receipt_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("receipt_date <= ?")
            params.append(end_date)
        if merchant_query.strip():
            clauses.append("merchant LIKE ? ESCAPE '\\' COLLATE NOCASE")
            escaped = merchant_query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id, receipt_date, merchant, total_cents, created_at, image_path, processed_image_path, "
                f"original_ocr_text, proposed_date, proposed_merchant, proposed_total_cents, receipt_format, source_id "
                f"FROM receipts {where} ORDER BY receipt_date DESC, id DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_receipt(self, receipt_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM receipts WHERE id = ?", (int(receipt_id),)).fetchone()
        return dict(row) if row else None

    def date_bounds(self) -> tuple[str | None, str | None]:
        with self._connect() as connection:
            row = connection.execute("SELECT MIN(receipt_date), MAX(receipt_date) FROM receipts").fetchone()
        return row[0], row[1]


def re_safe_id(value: str) -> str:
    # source_id normalmente es UUID; filtra cualquier carácter no seguro de un nombre de archivo.
    safe = "".join(character for character in str(value) if character.isalnum() or character in "-_")
    if not safe or len(safe) > 80:
        raise ValueError("Identificador de origen no válido.")
    return safe
