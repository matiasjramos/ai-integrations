import pytest

from phone_store_assistant import config
from phone_store_assistant.config import load_settings

ENV_NAMES = [
    "CLAUDE_MODEL", "CLAUDE_EFFORT", "GOOGLE_SERVICE_ACCOUNT_FILE", "GOOGLE_SHEET_ID",
    "GOOGLE_SHEET_WORKSHEET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "LEADS_DB_PATH",
    "CATALOG_JSON_PATH",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)  # ignore any local .env
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults():
    s = load_settings()
    assert s.anthropic_model == "claude-opus-5-5"
    assert s.effort == "medium"
    assert s.google_sheet_worksheet == "catalog"
    assert s.leads_db_path == "leads.db"
    assert s.telegram_bot_token is None
    assert s.catalog_json_path.name == "catalog.json"
    assert s.catalog_json_path.is_absolute()
    assert s.catalog_json_path.exists()


def test_catalog_path_independent_of_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert load_settings().catalog_json_path.exists()


def test_empty_strings_are_unset(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("CLAUDE_EFFORT", "")
    s = load_settings()
    assert s.anthropic_model == "claude-opus-5-5"
    assert s.telegram_bot_token is None
    assert s.effort == "medium"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("CLAUDE_EFFORT", "high")
    s = load_settings()
    assert s.anthropic_model == "claude-haiku-5-5"
    assert s.effort == "high"


def test_invalid_effort_raises(monkeypatch):
    monkeypatch.setenv("CLAUDE_EFFORT", "extreme")
    with pytest.raises(ValueError):
        load_settings()
