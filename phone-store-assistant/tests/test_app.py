from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from phone_store_assistant import chat, config
from phone_store_assistant.chat import ChatError


APP = Path(__file__).resolve().parent.parent / "app.py"


class FakeSession:
    def __init__(self, reply="Hello from the fake assistant", error=None):
        self.reply, self.error = reply, error
        self.usage = {"input_tokens": 7, "output_tokens": 3}

    def send(self, text):
        if self.error:
            raise self.error
        return self.reply


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    import streamlit as st

    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "leads.db"))
    for name in ("GOOGLE_SERVICE_ACCOUNT_FILE", "GOOGLE_SHEET_ID", "TELEGRAM_BOT_TOKEN",
                 "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    st.cache_resource.clear()  # resources are cached per process; isolate tests
    yield
    st.cache_resource.clear()


def _run(monkeypatch, session):
    # app.py looks the factory up on the chat module, so patch it there.
    monkeypatch.setattr(chat, "create_chat_session", lambda *a, **k: session)
    return AppTest.from_file(str(APP), default_timeout=30).run()


def test_renders_without_exception(monkeypatch):
    at = _run(monkeypatch, FakeSession())
    assert not at.exception
    assert not at.error


def test_message_shows_reply(monkeypatch):
    at = _run(monkeypatch, FakeSession())
    at.chat_input[0].set_value("Do you have iPhones?").run()
    assert not at.exception
    texts = [m.markdown[0].value for m in at.chat_message]
    assert "Do you have iPhones?" in texts
    assert "Hello from the fake assistant" in texts


def test_chat_error_shows_error(monkeypatch):
    at = _run(monkeypatch, FakeSession(error=ChatError("Service unavailable, try again.")))
    at.chat_input[0].set_value("hi").run()
    assert not at.exception
    assert [e.value for e in at.error] == ["Service unavailable, try again."]


def test_missing_key_shows_setup(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    at = _run(monkeypatch, FakeSession())
    assert not at.exception
    assert any("Setup needed" in w.value for w in at.warning)
    assert len(at.chat_input) == 0
