"""Conexiones SQLite y migraciones; no carga datos de prueba."""

import sqlite3
import unicodedata
from pathlib import Path


def connect(path):
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.create_function("fold", 1, lambda value: "".join(
        char for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    ).casefold(), deterministic=True)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db(path):
    if str(path) != ':memory:':
        Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("La base usa una versión más nueva que esta aplicación.")
        if version == 0:
            conn.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
            conn.commit()
    finally:
        conn.close()
