import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 1. Setup
load_dotenv()
db = SQLDatabase.from_uri("sqlite:///data/test_db.sqlite")
llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0)

# --- PROMPTURI ---

# A. Generare SQL inițial
initial_system = """You are an SQL expert. Write a SQLite query for the following question.
Schema: {schema}

RULES:
1. Return ONLY the SQL query.
2. If the user asks for a column that does NOT exist, do NOT invent it.
3. If the request is impossible based on the schema, try to select the most relevant available columns.
"""
initial_prompt = ChatPromptTemplate.from_messages(
    [("system", initial_system), ("human", "{question}")]
)

# B. Auto-Corecție (Erori Tehnice)
correction_system = """You are an SQL debugger.
The previous query: {original_query}
Caused the error: {error_message}
Schema: {schema}
Fix the SQL query to resolve the error. Return ONLY the corrected SQL."""
correction_prompt = ChatPromptTemplate.from_messages(
    [("system", correction_system), ("human", "Fix this query.")]
)

# C. Feedback Uman (Erori Logice)
feedback_system = """You are an SQL assistant refining a query based on user feedback.
Original Question: {question}
Previous SQL (Rejected): {original_query}
User Feedback (Why it was wrong): {feedback}
Schema: {schema}

INSTRUCTIONS:
1. Adjust the SQL query to satisfy the user's feedback.
2. If the user says a column doesn't exist, remove it from the SELECT list.
3. Return ONLY the corrected SQL query.
"""
feedback_prompt = ChatPromptTemplate.from_messages(
    [("system", feedback_system), ("human", "Fix the query based on my feedback.")]
)

# D. Răspuns Final (Anti-Halucinații)
answer_prompt = ChatPromptTemplate.from_template(
    """You are a data assistant. Read the SQL Query and the SQL Result to answer the User Question.

    User Question: {question}
    SQL Query Used: {query}
    SQL Result: {result}

    CRITICAL INSTRUCTIONS FOR THE ANSWER:
    1. Your answer must be based ONLY on the 'SQL Result'.
    2. Look at the 'SQL Query Used'. If it selects ONLY 'name', do NOT mention 'age', 'date', or other criteria in your text.
    3. If the user asked to sort by 'age', but the query sorts by 'signup_date' (or nothing), DO NOT claim you sorted by age. Just list the names found.
    4. Be literal. Do not hallucinate columns that are not in the Result.

    Answer in Romanian:"""
)

# --- FUNCTII AJUTATOARE ---


def clean_sql(text):
    return text.replace("```sql", "").replace("```", "").strip()


def run_query_safe(query):
    try:
        res = db.run(query)
        return res, None
    except Exception as e:
        return None, str(e)


# --- LOGICA DE EXECUTIE (PIPELINE) ---


def execute_and_summarize(sql_query, user_question):
    schema_text = db.get_table_info()
    current_sql = sql_query
    MAX_RETRIES = 3

    for attempt in range(MAX_RETRIES):
        print(f"   ⚙️ Executare SQL: {current_sql}")
        result, error = run_query_safe(current_sql)

        if error is None:
            # SUCCES
            chain_answer = answer_prompt | llm | StrOutputParser()
            final_answer = chain_answer.invoke(
                {"question": user_question, "result": result, "query": current_sql}
            )
            return final_answer, current_sql
        else:
            # EROARE TEHNICĂ - Auto-Corecție
            print(f"   ❌ Eroare tehnică: {error}")
            chain_fix = correction_prompt | llm | StrOutputParser()
            current_sql = clean_sql(
                chain_fix.invoke(
                    {
                        "original_query": current_sql,
                        "error_message": error,
                        "schema": schema_text,
                    }
                )
            )

    return "Eroare: Nu s-a putut genera un SQL valid.", None


def initial_generation(user_question):
    schema_text = db.get_table_info()
    print(f"🔄 Generare SQL inițial...")
    chain = initial_prompt | llm | StrOutputParser()
    sql = clean_sql(chain.invoke({"schema": schema_text, "question": user_question}))
    return execute_and_summarize(sql, user_question)


def feedback_generation(user_question, old_sql, user_feedback):
    schema_text = db.get_table_info()
    print(f"\n🔄 Regenerare SQL bazată pe feedback...")

    chain = feedback_prompt | llm | StrOutputParser()
    new_sql = clean_sql(
        chain.invoke(
            {
                "question": user_question,
                "original_query": old_sql,
                "feedback": user_feedback,
                "schema": schema_text,
            }
        )
    )

    return execute_and_summarize(new_sql, user_question)
