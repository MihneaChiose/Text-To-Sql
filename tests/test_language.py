"""Tests for response language detection and prompt selection."""

import os

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

os.environ.setdefault(
    "OPENAI_API_KEY",
    "sk-test-placeholder-not-a-real-key",
)

import robust_sql_chain as sql_chain


@pytest.mark.parametrize(
    "question,expected_language",
    [
        (
            "Care este cel mai scump produs?",
            "Romanian",
        ),
        (
            "Arata toate produsele si preturile.",
            "Romanian",
        ),
        (
            "Cati utilizatori au plasat comenzi?",
            "Romanian",
        ),
        (
            "Show all products",
            "English",
        ),
        (
            "Which product is the most expensive?",
            "English",
        ),
        (
            "What is the total spent by each user?",
            "English",
        ),
    ],
)
def test_language_detection(question, expected_language):
    assert sql_chain.detect_answer_language(question) == expected_language


@pytest.mark.parametrize(
    "question,expected_language",
    [
        ("Arata produsele", "Romanian"),
        ("Show products", "English"),
    ],
)
def test_answer_prompt_uses_detected_language(
    monkeypatch,
    question,
    expected_language,
):
    captured = {}

    def fake_response(prompt):
        captured["system"] = prompt.to_messages()[0].content

        return AIMessage(content="Test response")

    monkeypatch.setattr(
        sql_chain,
        "llm",
        RunnableLambda(fake_response),
    )

    monkeypatch.setattr(
        sql_chain,
        "get_schema",
        lambda: "CREATE TABLE products (name TEXT);",
    )

    monkeypatch.setattr(
        sql_chain,
        "run_query_safe",
        lambda query: ("[('Laptop Gaming',)]", None),
    )

    answer, query = sql_chain.execute_and_summarize(
        "SELECT name FROM products;",
        question,
    )

    assert answer == "Test response"
    assert query == "SELECT name FROM products;"

    assert f"The required answer language is {expected_language}." in captured["system"]
