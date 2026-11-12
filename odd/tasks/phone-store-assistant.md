# Feature: phone-store-assistant

Locator: `odd/tasks/phone-store-assistant.md` · Engram mirror: `odd/phone-store-assistant/tasks`

## Objective

Chat assistant for a phone store that answers questions from a real catalog (Google Sheets, JSON fallback) using Claude tool use, detects real buying intent, saves a lead to SQLite and notifies a seller on Telegram.

## Why

Portfolio project #1 claimed in the MAIPU application ("Desarrolladores de Integraciones de IA"). Every claim must be true in code: Sheets + JSON catalog, lead detection, handoff to seller.

## Scope

- `phone-store-assistant/` inside the `ai-integrations` monorepo.
- Python 3.11+, `anthropic` SDK, `gspread`, `streamlit`, SQLite, `pytest`, `python-dotenv`.
- Fake catalog data only.

## Constraints

- Model `claude-opus-5-5` default, `claude-haiku-5-5` via `CLAUDE_MODEL` env var.
- `tool_choice` auto (forced returns 400), no prefill, thinking adaptive (default on Opus 5.5), effort set explicitly.
- All tools `strict: true`.
- Manual agentic loop (no beta tool runner) so the loop is explainable.
- `.env` never committed; no credentials entered by the assistant.
- Commits: conventional, no AI attribution.

## Design

- Ports/adapters: `CatalogRepository` (Sheets, JSON, Fallback), `LeadRepository` (SQLite), `Notifier` (Telegram, Null).
- `tools.py`: schemas + dispatcher; `agent.py`: loop; `app.py`: Streamlit UI.
- Hallucination guards: system prompt (only tool data) + code-side validation (`create_lead` rejects unknown product ids).
- Cost: prompt caching on stable prefix (tools + system), effort configurable.

## TDD

Mode: off (no project/session config, not requested). Source: default. Runner: `pytest`. Ordinary functional checks per task.

## Delivery

Strategy: ask-on-risk. Forecast ~600 authored lines incl. tests → slices per task commit.

## Tasks

- [x] T1 Repo scaffold: root `.gitignore`, task doc, project skeleton (`pyproject`/requirements, `.env.example`, sample `catalog.json`). Route: inline (mechanical).
- [x] T2 Domain + adapters: catalog (JSON, Sheets, Fallback), leads (SQLite), notifier (Telegram/Null) + unit tests. Route: delegated writer (2+ non-trivial files).
- [ ] T3 Tools + agent loop (Claude tool use, strict tools, caching, error handling) + tests with a fake client. Route: delegated writer.
- [ ] T4 Streamlit chat UI + project README (problem, diagram, run, cost, improvements). Route: TBD.
- [ ] T5 Manual end-to-end run with real API key (user) + secret scan before push.

## Acceptance criteria

- Asking for a phone returns only catalog products/prices (no invented items).
- Sheets failure → JSON fallback, logged.
- Clear buying intent → lead row in SQLite + Telegram message (or logged no-op when Telegram unset).
- `pytest` green without network or API key.

## Progress

- T1 done (commit fb07b72). `.env.example` blocked by permission deny rule on `.env*`; pending user action.
- T2 done: 23 tests pass (`.venv/Scripts/python -m pytest -q`, parent re-ran). Malformed Sheets row fails whole load → FallbackCatalog serves JSON. Engram mirror pending (ambiguous session).

## Next step

T3 tools + agent loop (delegated writer).
