"""Settings loaded from the environment.

ANTHROPIC_API_KEY is deliberately absent: the Anthropic SDK reads it itself,
so the key never travels through our own objects (or logs).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
VALID_EFFORTS = {"low", "medium", "high"}


@dataclass(frozen=True)
class Settings:
    anthropic_model: str
    effort: str
    google_service_account_file: str | None
    google_sheet_id: str | None
    google_sheet_worksheet: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    leads_db_path: str
    catalog_json_path: Path


def _get(name: str, default: str | None = None) -> str | None:
    """Empty strings count as unset (common with copied .env templates)."""
    value = os.getenv(name)
    return value if value else default


def load_settings() -> Settings:
    load_dotenv()
    effort = _get("CLAUDE_EFFORT", "medium")
    if effort not in VALID_EFFORTS:
        raise ValueError(f"CLAUDE_EFFORT must be one of {sorted(VALID_EFFORTS)}, got {effort!r}")
    # Resolve relative to the project, not the cwd, so it works from any launch dir.
    catalog_path = Path(_get("CATALOG_JSON_PATH") or PROJECT_DIR / "data" / "catalog.json")
    return Settings(
        anthropic_model=_get("CLAUDE_MODEL", "claude-opus-5-5"),
        effort=effort,
        google_service_account_file=_get("GOOGLE_SERVICE_ACCOUNT_FILE"),
        google_sheet_id=_get("GOOGLE_SHEET_ID"),
        google_sheet_worksheet=_get("GOOGLE_SHEET_WORKSHEET", "catalog"),
        telegram_bot_token=_get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_get("TELEGRAM_CHAT_ID"),
        leads_db_path=_get("LEADS_DB_PATH", "leads.db"),
        catalog_json_path=catalog_path,
    )
