"""Lanțul Text-to-SQL: generare, execuție, auto-corectare și feedback."""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from database import get_schema, run_query_safe

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    temperature=0,
)

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


def clean_sql(text: str) -> str:
    return text.replace("```sql", "").replace("```SQL", "").replace("```", "").strip()


def execute_and_summarize(sql_query: str, user_question: str):
    schema_text = get_schema()
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


def initial_generation(user_question: str):
    schema_text = get_schema()
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


def feedback_generation(
    user_question: str,
    old_sql: str,
    user_feedback: str,
):
    schema_text = get_schema()
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
