"""Tests for Text-to-SQL generation, execution, repair and refinement."""

import os

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


# Tests must not make real OpenAI API calls.
os.environ.setdefault(
    "OPENAI_API_KEY",
    "sk-test-placeholder-not-a-real-key",
)

import robust_sql_chain as sql_chain


# ======================================
# Mock OpenAI Model
# ======================================


@pytest.fixture
def fake_model(monkeypatch):
    """
    Replace the real LLM with predictable responses.

    Supports SQL generation, SQL correction,
    query refinement and multilingual answers.
    """

    calls = []

    def respond(prompt):
        system_text = prompt.to_messages()[0].content
        calls.append(system_text)

        # SQL self-repair
        if "SQL debugger" in system_text:
            return AIMessage(content="SELECT product_name FROM products;")

        # Query refinement
        if "refining a query" in system_text:
            return AIMessage(
                content=("SELECT product_name FROM products WHERE price > 100;")
            )

        # Initial SQL generation
        if "SQL expert" in system_text:
            return AIMessage(content="SELECT product_name FROM products;")

        # Natural-language answer generation
        if "professional database assistant" in system_text:
            if "The required answer language is Romanian." in system_text:
                return AIMessage(content="Am găsit produsele solicitate.")

            if "The required answer language is English." in system_text:
                return AIMessage(content="I found the requested products.")

            raise AssertionError("The answer language was not specified correctly.")

        raise AssertionError("Unexpected prompt sent to the mock model")

    monkeypatch.setattr(
        sql_chain,
        "llm",
        RunnableLambda(respond),
    )

    return calls


# ======================================
# SQL Cleaning
# ======================================


def test_clean_sql_removes_markdown():
    sql = sql_chain.clean_sql("```sql\nSELECT * FROM products;\n```")

    assert sql == "SELECT * FROM products;"


# ======================================
# SQL Execution
# ======================================


def test_select_query_returns_data():
    result, error = sql_chain.run_query_safe("SELECT product_name FROM products;")

    assert error is None
    assert "Laptop Gaming" in result


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM products;",
        "UPDATE products SET price = 0;",
        "DROP TABLE products;",
        "WITH item AS (SELECT 1) DELETE FROM products;",
    ],
)
def test_write_queries_are_blocked(query):
    before, before_error = sql_chain.run_query_safe("SELECT COUNT(*) FROM products;")

    assert before_error is None

    _, error = sql_chain.run_query_safe(query)

    after, after_error = sql_chain.run_query_safe("SELECT COUNT(*) FROM products;")

    assert error is not None
    assert after_error is None
    assert after == before


def test_invalid_sql_returns_error():
    _, error = sql_chain.run_query_safe("SELECT nonexistent_column FROM products;")

    assert error is not None


# ======================================
# Initial SQL Generation
# ======================================


def test_initial_generation_without_api_calls(fake_model):
    answer, query = sql_chain.initial_generation("Show all products")

    assert answer == "I found the requested products."
    assert query == "SELECT product_name FROM products;"

    # SQL generation + answer generation
    assert len(fake_model) == 2

    # The answer prompt must specify English.
    assert any(
        "The required answer language is English." in call for call in fake_model
    )


# ======================================
# Query Refinement
# ======================================


def test_feedback_generation_without_api_calls(fake_model):
    answer, query = sql_chain.feedback_generation(
        "Show all products",
        "SELECT product_name FROM products;",
        "Only show products above 100",
    )

    assert answer == "I found the requested products."

    assert query == ("SELECT product_name FROM products WHERE price > 100;")

    # Query refinement + answer generation
    assert len(fake_model) == 2


# ======================================
# Automatic SQL Self-Repair
# ======================================


def test_self_repair_after_sql_error(fake_model):
    answer, query = sql_chain.execute_and_summarize(
        "SELECT nonexistent_column FROM products;",
        "Show all products",
    )

    assert answer == "I found the requested products."
    assert query == "SELECT product_name FROM products;"

    repair_calls = sum("SQL debugger" in call for call in fake_model)

    assert repair_calls == 1


# ======================================
# Self-Repair Retry Limit
# ======================================


def test_self_repair_stops_after_three_attempts(
    monkeypatch,
):
    repair_calls = []

    def always_bad(prompt):
        system_text = prompt.to_messages()[0].content

        assert "SQL debugger" in system_text

        repair_calls.append(system_text)

        return AIMessage(content="SELECT nonexistent_column FROM products;")

    monkeypatch.setattr(
        sql_chain,
        "llm",
        RunnableLambda(always_bad),
    )

    answer, query = sql_chain.execute_and_summarize(
        "SELECT nonexistent_column FROM products;",
        "Show all products",
    )

    assert query is None

    # The question is in English, so the error
    # message must also be in English.
    assert answer == "I could not execute a valid SQL query."

    # Three execution attempts, two corrections
    assert len(repair_calls) == 2
