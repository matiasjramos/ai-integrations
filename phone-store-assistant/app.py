"""Streamlit chat demo: composition root + UI. Run with `streamlit run app.py`."""

import logging
import os

import streamlit as st

from phone_store_assistant import chat
from phone_store_assistant.catalog import FallbackCatalog, build_catalog
from phone_store_assistant.chat import ChatError
from phone_store_assistant.config import load_settings
from phone_store_assistant.leads import SqliteLeadRepository
from phone_store_assistant.notifier import build_notifier
from phone_store_assistant.tools import ToolExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Env var names only; values are never read into the UI (presence check).
_KEY_VARS = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "claude": ("ANTHROPIC_API_KEY",),
}

st.set_page_config(page_title="Phone Store Assistant", page_icon=":iphone:")


def _has_api_key(provider: str) -> bool:
    return any(os.getenv(name) for name in _KEY_VARS[provider])


@st.cache_resource
def get_resources():
    """Shared across browser sessions; each session still gets its own ChatSession."""
    settings = load_settings()
    catalog = build_catalog(settings)
    leads = SqliteLeadRepository(settings.leads_db_path)
    executor = ToolExecutor(catalog, leads, build_notifier(settings))
    return settings, catalog, leads, executor


def _reset() -> None:
    st.session_state.pop("session", None)
    st.session_state["messages"] = []


try:
    settings, catalog, leads, executor = get_resources()
except ValueError as exc:  # config validation messages are safe (no secrets)
    st.error(f"Configuration error: {exc}")
    st.stop()

st.title("Phone Store Assistant")
st.caption("Demo with fake catalog and fake leads.")

if not _has_api_key(settings.llm_provider):
    names = " or ".join(_KEY_VARS[settings.llm_provider])
    st.warning(
        f"Setup needed: provider `{settings.llm_provider}` requires `{names}` "
        "in your environment or `.env` file. Set it and restart the app."
    )
    st.stop()

if "session" not in st.session_state:
    try:
        st.session_state["session"] = chat.create_chat_session(settings, executor)
    except Exception as exc:  # SDK/client setup can fail in many ways; keep the page alive
        logger.error("Chat session construction failed: %s", type(exc).__name__)
        st.error("Could not start the assistant. Check your provider configuration and restart.")
        st.stop()
    st.session_state.setdefault("messages", [])
session = st.session_state["session"]

model = settings.gemini_model if settings.llm_provider == "gemini" else settings.anthropic_model
with st.sidebar:
    st.subheader("Session")
    st.write(f"Provider: `{settings.llm_provider}`")
    st.write(f"Model: `{model}`")
    source = getattr(catalog, "last_source", None) if isinstance(catalog, FallbackCatalog) else None
    st.write(f"Catalog source: `{source or 'json'}`")
    usage = getattr(session, "usage", None)
    if usage:
        st.write("Token usage")
        st.json(usage)
    st.button("New conversation", on_click=_reset)
    with st.expander("Recent leads (seller view)"):
        try:
            recent = leads.list_recent(10)
        except Exception as exc:  # a broken leads DB must not take the chat down
            logger.error("Recent leads query failed: %s", type(exc).__name__)
            st.warning("Could not load recent leads.")
            recent = None
        if recent == []:
            st.write("No leads yet.")
        for lead in recent or []:
            st.write(f"{lead.name} | {lead.product_id} | {lead.created_at:%Y-%m-%d %H:%M}")

for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask about phones..."):
    # The slot lets us retract the bubble: a failed turn is rolled back in the session
    # (and dropped from our history), so it must not stay on screen without a reply.
    user_slot = st.empty()
    with user_slot.container(), st.chat_message("user"):
        st.markdown(prompt)
    try:
        with st.spinner("Thinking..."):
            reply = session.send(prompt)
    except ChatError as exc:
        user_slot.empty()
        st.error(str(exc))  # ChatError messages are safe by contract
    else:
        st.session_state["messages"].append({"role": "user", "content": prompt})
        st.session_state["messages"].append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"):
            st.markdown(reply)
