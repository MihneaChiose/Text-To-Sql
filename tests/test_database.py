"""Teste pentru accesul read-only la SQLite, fără apeluri OpenAI."""

import pytest
from sqlalchemy.exc import SQLAlchemyError

from database import MAX_RESULT_ROWS, engine, get_schema, run_query_safe


def test_schema_contains_expected_tables():
    schema = get_schema()
    assert "CREATE TABLE" in schema.upper()
    assert "products" in schema
    assert "orders" in schema
    assert "users" in schema


def test_select_returns_results():
    result, error = run_query_safe("SELECT COUNT(*) FROM products;")
    assert error is None
    assert result is not None
    assert "(4,)" in result


def test_empty_query_is_rejected():
    result, error = run_query_safe("  ")
    assert result is None
    assert error is not None


def test_multiple_sql_statements_are_rejected():
    result, error = run_query_safe("SELECT * FROM products; DELETE FROM products;")
    assert result is None
    assert error is not None


def test_read_only_connection_blocks_writes_directly():
    with engine.connect() as connection:
        with pytest.raises(SQLAlchemyError):
            connection.exec_driver_sql("DELETE FROM products")


def test_large_results_are_truncated():
    query = """
        WITH RECURSIVE sequence(n) AS (
            SELECT 1
            UNION ALL
            SELECT n + 1 FROM sequence WHERE n < 105
        )
        SELECT n FROM sequence;
    """
    result, error = run_query_safe(query)
    assert error is None
    assert result is not None
    assert f"[Results truncated to {MAX_RESULT_ROWS} rows]" in result
    assert "(100,)" in result
    assert "(101,)" not in result
