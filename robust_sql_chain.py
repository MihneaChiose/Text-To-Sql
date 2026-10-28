"""Text-to-SQL: generation, execution, self-repair and query refinement."""

import os
import re
import unicodedata
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from database import get_schema, run_query_safe


# ======================================
# Configuration
# ======================================

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    temperature=0,
)


# ======================================
# Language Detection
# ======================================

ROMANIAN_WORDS = {
    "care",
    "ce",
    "cat",
    "cate",
    "cati",
    "afiseaza",
    "arata",
    "vreau",
    "spune",
    "gaseste",
    "poti",
    "imi",
    "vad",
    "este",
    "sunt",
    "au",
    "din",
    "in",
    "pe",
    "cu",
    "si",
    "sau",
    "pentru",
    "mai",
    "cel",
    "cea",
    "cei",
    "cele",
    "fiecare",
    "toti",
    "toate",
    "dupa",
    "numarul",
    "numele",
    "utilizatori",
    "utilizatorii",
    "produse",
    "produsele",
    "produs",
    "produsul",
    "comenzi",
    "comenzile",
    "comanda",
    "pret",
    "pretul",
    "preturi",
    "preturile",
    "scump",
    "ieftin",
    "suma",
    "totalul",
    "ordoneaza",
    "descrescator",
    "crescator",
    "listeaza",
}

ENGLISH_WORDS = {
    "show",
    "list",
    "display",
    "give",
    "find",
    "which",
    "what",
    "how",
    "many",
    "who",
    "where",
    "when",
    "are",
    "is",
    "have",
    "has",
    "the",
    "all",
    "each",
    "every",
    "with",
    "and",
    "from",
    "of",
    "to",
    "me",
    "by",
    "more",
    "than",
    "less",
    "above",
    "below",
    "over",
    "under",
    "products",
    "product",
    "users",
    "user",
    "orders",
    "order",
    "price",
    "prices",
    "expensive",
    "cheapest",
    "total",
    "spent",
    "ordered",
    "sort",
    "descending",
    "ascending",
    "cost",
    "costs",
}


def detect_answer_language(question: str) -> str:
    """Identify Romanian or English using lightweight word matching."""

    normalized = unicodedata.normalize(
        "NFKD",
        question.casefold(),
    )

    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )

    words = re.findall(r"[a-z]+", normalized)

    romanian_score = sum(word in ROMANIAN_WORDS for word in words)

    english_score = sum(word in ENGLISH_WORDS for word in words)

    if romanian_score > english_score:
        return "Romanian"

    if english_score > romanian_score:
        return "English"

    # Use Romanian for ambiguous questions with Romanian diacritics.
    if any(character in question.casefold() for character in "ăâîșşțţ"):
        return "Romanian"

    # Default language for ambiguous or very short questions.
    return "English"


# ======================================
# Prompt Templates
# ======================================

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

Correct the query.
Return ONLY one read-only SELECT query.""",
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
1. Adjust the SQL according to the requested changes.
2. Use only columns that exist in the schema.
3. Return ONLY one read-only SELECT query.""",
        ),
        ("human", "Refine the previous query."),
    ]
)


answer_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a professional database assistant.

The required answer language is {language}.

LANGUAGE RULES:
1. Answer entirely in {language}.
2. Never answer in Spanish or any other language.
3. Do not mix Romanian and English in the explanation.
4. Preserve database values, product names and SQL identifiers exactly.
5. Do not translate SQL keywords or stored database values.

ACCURACY RULES:
1. Base your answer ONLY on the SQL query and SQL result.
2. Do not invent missing information.
3. Do not claim filtering or sorting that was not performed.
4. If the result is empty, explain that no matching records were found.
5. Keep the answer clear, concise and professional.

Follow the required answer language strictly.
""",
        ),
        (
            "human",
            """User question: {question}

Executed SQL query:
{query}

SQL result:
{result}

Explain the result in the required language.""",
        ),
    ]
)


# ======================================
# SQL Cleaning
# ======================================


def clean_sql(text: str) -> str:
    return text.replace("```sql", "").replace("```SQL", "").replace("```", "").strip()


# ======================================
# SQL Execution and Self-Repair
# ======================================


def execute_and_summarize(
    sql_query: str,
    user_question: str,
):
    schema_text = get_schema()
    current_sql = sql_query
    max_retries = 3

    answer_language = detect_answer_language(user_question)

    for attempt in range(1, max_retries + 1):
        print(f"Attempt {attempt}: {current_sql}")

        result, error = run_query_safe(current_sql)

        if error is None:
            answer_chain = answer_prompt | llm | StrOutputParser()

            answer = answer_chain.invoke(
                {
                    "question": user_question,
                    "query": current_sql,
                    "result": result,
                    "language": answer_language,
                }
            )

            return answer, current_sql

        print(f"SQL error: {error}")

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

    failure_messages = {
        "Romanian": "Nu am reușit să execut o interogare SQL validă.",
        "English": "I could not execute a valid SQL query.",
    }

    return failure_messages[answer_language], None


# ======================================
# Initial SQL Generation
# ======================================


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

    return execute_and_summarize(
        sql,
        user_question,
    )


# ======================================
# Query Refinement
# ======================================


def feedback_generation(
    user_question: str,
    old_sql: str,
    user_feedback: str,
):
    schema_text = get_schema()

    refinement_chain = feedback_prompt | llm | StrOutputParser()

    new_sql = clean_sql(
        refinement_chain.invoke(
            {
                "question": user_question,
                "original_query": old_sql,
                "feedback": user_feedback,
                "schema": schema_text,
            }
        )
    )

    return execute_and_summarize(
        new_sql,
        user_question,
    )
