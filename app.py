"""Streamlit interface for the Text-to-SQL Assistant."""

import logging

import streamlit as st
from openai import (
    APIConnectionError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)

from robust_sql_chain import (
    feedback_generation,
    initial_generation,
)


# ======================================
# Page Configuration
# ======================================

st.set_page_config(
    page_title="Text-to-SQL Assistant",
    page_icon="🗃️",
    layout="wide",
)

logger = logging.getLogger(__name__)

EXAMPLES = [
    ("Browse products", "Show all products and their prices."),
    ("Top-priced item", "Which product is the most expensive?"),
    ("Order totals", "What is the total amount spent by each user?"),
]


# ======================================
# Session State
# ======================================


def initialize_state() -> None:
    defaults = {
        "messages": [],
        "last_question": None,
        "last_sql": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ======================================
# Error Handling
# ======================================


def friendly_error(exc: Exception) -> str:
    """Return a safe and user-friendly error message."""

    if isinstance(exc, AuthenticationError):
        return "OpenAI authentication failed. Check OPENAI_API_KEY in your .env file."

    if isinstance(exc, RateLimitError):
        return (
            "The API rate limit or available quota was reached. "
            "Check OpenAI billing and limits."
        )

    if isinstance(exc, NotFoundError):
        return (
            "The configured OpenAI model was not found. "
            "Check OPENAI_MODEL in your .env file."
        )

    if isinstance(exc, APIConnectionError):
        return "Cannot connect to OpenAI right now. Check your internet connection."

    return "The request could not be completed. Check the VS Code terminal for details."


# ======================================
# Message Rendering
# ======================================


def render_message(message: dict) -> None:
    """Display a message from conversation history."""

    with st.chat_message(message["role"]):
        if message.get("error"):
            st.error(message["content"])
        else:
            st.markdown(message["content"])

        if message.get("sql"):
            with st.expander("View generated SQL"):
                st.code(
                    message["sql"],
                    language="sql",
                )


initialize_state()


# ======================================
# Sidebar - Query Refinement
# ======================================

with st.sidebar:
    st.subheader(
        "Refine previous query",
        anchor=False,
    )

    if st.session_state.last_sql:
        st.caption(
            "Describe how you would like to modify the previously generated SQL query."
        )

        with st.form(
            "refinement_form",
            clear_on_submit=True,
        ):
            refinement_text = st.text_area(
                "Requested changes",
                placeholder=("For example: Only include products above 100."),
                height=110,
            )

            refinement_submitted = st.form_submit_button("Update query")

        if refinement_submitted:
            refinement = refinement_text.strip()

            if not refinement:
                st.warning("Please describe the changes you want to make.")

            else:
                with st.spinner("Updating SQL query..."):
                    try:
                        answer, new_sql = feedback_generation(
                            st.session_state.last_question,
                            st.session_state.last_sql,
                            refinement,
                        )

                    except Exception as exc:
                        logger.exception("Query refinement failed")

                        st.error(friendly_error(exc))

                    else:
                        st.session_state.messages.append(
                            {
                                "role": "user",
                                "content": (f"Refinement request: {refinement}"),
                            }
                        )

                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "content": answer,
                                "sql": new_sql,
                            }
                        )

                        if new_sql:
                            st.session_state.last_sql = new_sql

                        st.rerun()

    else:
        st.caption("Submit a question to enable query refinement.")

    st.divider()

    # ======================================
    # Clear Conversation
    # ======================================

    if st.button(
        "Clear conversation",
        width="stretch",
    ):
        st.session_state.messages = []
        st.session_state.last_question = None
        st.session_state.last_sql = None

        st.rerun()


# ======================================
# Main Interface
# ======================================

st.title(
    "Text-to-SQL Assistant",
    anchor=False,
)

st.caption(
    "Ask questions about your data in natural language. "
    "The assistant generates read-only SQL "
    "and explains the results."
)


# ======================================
# Example Questions
# ======================================

example_question = None

if not st.session_state.messages:
    st.subheader(
        "Try an example",
        anchor=False,
    )

    columns = st.columns(3)

    for index, (label, question) in enumerate(EXAMPLES):
        if columns[index].button(
            label,
            key=f"example_{index}",
            width="stretch",
        ):
            example_question = question


# ======================================
# Conversation History
# ======================================

for saved_message in st.session_state.messages:
    render_message(saved_message)


# ======================================
# Chat Input
# ======================================

chat_question = st.chat_input("Ask a question about the database...")

question = example_question or chat_question

if question and question.strip():
    question = question.strip()

    st.session_state.messages.append(
        {
            "role": "user",
            "content": question,
        }
    )

    st.session_state.last_question = None
    st.session_state.last_sql = None

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Generating and executing SQL..."):
            try:
                answer, sql_used = initial_generation(question)

            except Exception as exc:
                logger.exception("Initial query generation failed")

                error_text = friendly_error(exc)

                st.error(error_text)

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": error_text,
                        "error": True,
                    }
                )

            else:
                st.markdown(answer)

                if sql_used:
                    with st.expander("View generated SQL"):
                        st.code(
                            sql_used,
                            language="sql",
                        )

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": answer,
                        "sql": sql_used,
                    }
                )

                if sql_used:
                    st.session_state.last_question = question
                    st.session_state.last_sql = sql_used

    st.rerun()
