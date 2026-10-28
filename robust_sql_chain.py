import os
import re
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.utilities import SQLDatabase
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy import create_engine


# ==============================
# Configuration
# ==============================

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "test_db.sqlite"

load_dotenv(PROJECT_ROOT / ".env")

if not DB_PATH.is_file():
    raise FileNotFoundError(
        "Baza de date lipsește. Rulează mai întâi: python create_test_db.py"
    )


def connect_read_only():
    connection = sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


engine = create_engine("sqlite://", creator=connect_read_only)

db = SQLDatabase(engine)

llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), temperature=0)


# ==============================
# Prompt Templates
# ==============================

initial_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an SQL expert. Write a SQLite query for the question.
Schema: {schema}

Rules:
1. Return ONLY one SQL query, without explanations.
2. Generate only read-only SELECT queries (WITH ... SELECT is allowed).
3. Never invent columns that are not in the schema.
4. If the question cannot be answered with the available columns, select only
   relevant existing columns; do not fabricate values.
""",
        ),
        ("human", "{question}"),
    ]
)


correction_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an SQL debugger.
Previous query: {original_query}
Database error: {error_message}
Schema: {schema}
Correct the query. Return ONLY one read-only SELECT query.""",
        ),
        ("human", "Fix this query."),
    ]
)


feedback_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an SQL assistant refining a query based on user feedback.
Original question: {question}
Previous SQL (rejected): {original_query}
User feedback: {feedback}
Schema: {schema}

Rules:
1. Adjust the SQL according to the feedback.
2. Use only columns that exist in the schema.
3. Return ONLY one read-only SELECT query.""",
        ),
        ("human", "Fix the query based on my feedback."),
    ]
)


answer_prompt = ChatPromptTemplate.from_template(
    """You are a data assistant.
User question: {question}
SQL query: {query}
SQL result: {result}

Rules:
1. Base your answer ONLY on the SQL result.
2. Never claim a column was used for filtering or sorting if it was not.
3. Do not invent missing information.
4. Answer in Romanian.
"""
)


# ==============================
# Helper Functions
# ==============================


def clean_sql(text: str) -> str:
    return text.replace("```sql", "").replace("```SQL", "").replace("```", "").strip()


def run_query_safe(query: str):
    query = query.strip()

    if not re.match(r"^(SELECT|WITH)\b", query, flags=re.IGNORECASE):
        return None, "Sunt permise doar interogări de citire (SELECT)."

    try:
        return db.run(query), None

    except Exception as exc:
        return None, str(exc)


# ==============================
# SQL Execution and Self-Repair
# ==============================


def execute_and_summarize(sql_query: str, user_question: str):
    schema_text = db.get_table_info()
    current_sql = sql_query
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        print(f"Încercarea {attempt}: {current_sql}")

        result, error = run_query_safe(current_sql)

        if error is None:
            answer_chain = answer_prompt | llm | StrOutputParser()

            answer = answer_chain.invoke(
                {
                    "question": user_question,
                    "query": current_sql,
                    "result": result,
                }
            )

            return answer, current_sql

        print(f"Eroare SQL: {error}")

        if attempt < max_retries:
            correction_chain = correction_prompt | llm | StrOutputParser()

            current_sql = clean_sql(
                correction_chain.invoke(
                    {
                        "original_query": current_sql,
                        "error_message": error,
                        "schema": schema_text,
                    }
                )
            )

    return "Nu am reușit să execut o interogare SQL validă.", None


# ==============================
# Initial SQL Generation
# ==============================


def initial_generation(user_question: str):
    schema_text = db.get_table_info()

    generation_chain = initial_prompt | llm | StrOutputParser()

    sql = clean_sql(
        generation_chain.invoke(
            {
                "schema": schema_text,
                "question": user_question,
            }
        )
    )

    return execute_and_summarize(sql, user_question)


# ==============================
# Human Feedback
# ==============================


def feedback_generation(user_question: str, old_sql: str, user_feedback: str):
    schema_text = db.get_table_info()

    feedback_chain = feedback_prompt | llm | StrOutputParser()

    new_sql = clean_sql(
        feedback_chain.invoke(
            {
                "question": user_question,
                "original_query": old_sql,
                "feedback": user_feedback,
                "schema": schema_text,
            }
        )
    )

    return execute_and_summarize(new_sql, user_question)
