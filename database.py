"""Acces read-only la baza de date SQLite pentru aplicația Text-to-SQL."""

import re
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "test_db.sqlite"
MAX_RESULT_ROWS = 100


def _connect_read_only():
    """Deschide fiecare conexiune SQLite fără permisiuni de scriere."""
    if not DB_PATH.is_file():
        raise FileNotFoundError(
            "Baza de date lipsește. Rulează: python create_test_db.py"
        )

    connection = sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


engine = create_engine(
    "sqlite://",
    creator=_connect_read_only,
    poolclass=NullPool,
)


def get_schema() -> str:
    """Returnează definițiile tabelelor pe care le poate folosi modelul."""
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

    if not rows:
        raise RuntimeError("Baza de date nu conține tabele.")

    return "\n\n".join(f"{row[0]};" for row in rows if row[0])


def run_query_safe(query: str) -> tuple[str | None, str | None]:
    """Execută doar SQL de citire și returnează (rezultat, eroare)."""
    sql = query.strip()

    if not re.match(r"^(SELECT|WITH)\b", sql, flags=re.IGNORECASE):
        return None, "Sunt permise doar interogări de citire (SELECT)."

    try:
        with engine.connect() as connection:
            result = connection.exec_driver_sql(sql)
            rows = result.fetchmany(MAX_RESULT_ROWS + 1)

        truncated = len(rows) > MAX_RESULT_ROWS
        formatted = str([tuple(row) for row in rows[:MAX_RESULT_ROWS]])

        if truncated:
            formatted += f"\n[Results truncated to {MAX_RESULT_ROWS} rows]"

        return formatted, None

    except (SQLAlchemyError, sqlite3.Error, FileNotFoundError) as exc:
        return None, str(exc)
