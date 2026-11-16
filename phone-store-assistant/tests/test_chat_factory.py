import dataclasses

import pytest

from phone_store_assistant import config
from phone_store_assistant.chat import create_chat_session
from phone_store_assistant.claude_session import ClaudeChatSession
from phone_store_assistant.config import load_settings
from phone_store_assistant.gemini_session import GeminiChatSession


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    for name in ("LLM_PROVIDER", "GEMINI_MODEL", "MAX_TOOL_ITERATIONS"):
        monkeypatch.delenv(name, raising=False)


def test_defaults():
    s = load_settings()
    assert s.llm_provider == "gemini"
    assert s.gemini_model == "gemini-3.8-flash"
    assert s.max_tool_iterations == 6


def test_factory_picks_adapter_by_provider():
    s = load_settings()
    fake = object()
    assert isinstance(create_chat_session(s, None, client=fake), GeminiChatSession)
    claude = dataclasses.replace(s, llm_provider="claude")
    assert isinstance(create_chat_session(claude, None, client=fake), ClaudeChatSession)


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("MAX_TOOL_ITERATIONS", "3")
    s = load_settings()
    assert (s.llm_provider, s.max_tool_iterations) == ("claude", 3)


@pytest.mark.parametrize("name,value", [
    ("LLM_PROVIDER", "openai"),
    ("MAX_TOOL_ITERATIONS", "abc"),
    ("MAX_TOOL_ITERATIONS", "0"),
])
def test_invalid_values_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        load_settings()
