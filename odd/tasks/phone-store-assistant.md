# Feature: phone-store-assistant

Locator: `odd/tasks/phone-store-assistant.md` · Engram mirror: `odd/phone-store-assistant/tasks`

## Objective

Chat assistant for a phone store that answers questions from a real catalog (Google Sheets, JSON fallback) using LLM tool use (Gemini or Claude behind one port), detects real buying intent, saves a lead to SQLite and notifies a seller on Telegram.

## Why

Portfolio project #1 claimed in the MAIPU application ("Desarrolladores de Integraciones de IA"). Every claim must be true in code: Sheets + JSON catalog, lead detection, handoff to seller.

## Scope

- `phone-store-assistant/` inside the `ai-integrations` monorepo.
- Python 3.11+, `anthropic` and `google-genai` SDKs, `gspread`, `streamlit`, SQLite, `pytest`, `python-dotenv`.
- Fake catalog data only.

## Constraints

- Provider via `LLM_PROVIDER` (`gemini` default: free tier; `claude` optional). Gemini model `GEMINI_MODEL` (default `gemini-flash-latest`). Claude model `claude-opus-5-5` default, `claude-haiku-5-5` via `CLAUDE_MODEL`.
- Budget: zero cost. User decision (2026-11-13): run everything on free tiers; Claude adapter kept so the "API de Claude" claim stays true.
- `tool_choice` auto (forced returns 400), no prefill, thinking adaptive (default on Opus 5.5), effort set explicitly.
- All tools `strict: true`.
- Manual agentic loop (no beta tool runner) so the loop is explainable.
- `.env` never committed; no credentials entered by the assistant.
- Commits: conventional, no AI attribution.

## Design

- Ports/adapters: `CatalogRepository` (Sheets, JSON, Fallback), `LeadRepository` (SQLite), `Notifier` (Telegram, Null).
- `tools.py`: provider-neutral tool specs + executor; `ChatSession` port with `ClaudeChatSession` and `GeminiChatSession` adapters (each owns its native history + manual loop); `app.py`: Streamlit UI.
- Hallucination guards: system prompt (only tool data) + code-side validation (`create_lead` rejects unknown product ids).
- Cost: prompt caching on stable prefix (tools + system), effort configurable.

## TDD

Mode: off (no project/session config, not requested). Source: default. Runner: `pytest`. Ordinary functional checks per task.

## Delivery

Strategy: ask-on-risk. Forecast ~600 authored lines incl. tests → slices per task commit.

## Tasks

- [x] T1 Repo scaffold: root `.gitignore`, task doc, project skeleton (`pyproject`/requirements, `.env.example`, sample `catalog.json`). Route: inline (mechanical).
- [x] T2 Domain + adapters: catalog (JSON, Sheets, Fallback), leads (SQLite), notifier (Telegram/Null) + unit tests. Route: delegated writer (2+ non-trivial files).
- [x] T3 Tools + ChatSession port + Claude and Gemini adapters (manual tool loops, strict tools, caching, error handling) + tests with fake clients. Route: delegated writer (2+ non-trivial files). Scope revised 2026-11-13: Gemini added by user request.
- [x] T4 Streamlit chat UI + project README (problem, diagram, run, cost, improvements). Route: delegated writer (2 non-trivial files).
- [ ] T5 Manual end-to-end run with real API key (user) + secret scan before push.

## Acceptance criteria

- Asking for a phone returns only catalog products/prices (no invented items).
- Sheets failure → JSON fallback, logged.
- Clear buying intent → lead row in SQLite + Telegram message (or logged no-op when Telegram unset).
- `pytest` green without network or API key.

## Progress

- T1 done (commit fb07b72). `.env.example` blocked by permission deny rule on `.env*`; pending user action.
- T2 done: 23 tests pass (`.venv/Scripts/python -m pytest -q`, parent re-ran). Malformed Sheets row fails whole load → FallbackCatalog serves JSON. Engram mirror pending (ambiguous session).
- T2 review: medium risk, granted, approved + acknowledged (lineage review-097cb23b148c4105). Reviewed boundary → 59b3a0c. Non-blocking follow-ups: FallbackCatalog when both sources fail; JsonCatalog with non-list payload; config tests depend on data file; list_recent limit bounds; Sheets adapter boundaries.
- T3 done: 63 tests pass (parent re-ran). Both-sources catalog failure now handled as tool error. Unverified until T5: real Gemini/Claude calls; Gemini acceptance of `minimum` in schemas. Note: catalog loaded per tool call (one Sheets read per call) → caching candidate.
- T3 review (lineage review-b41e8b0f19db1584): granted. Reviewer flagged `httpx2` import as typo (BLOCKER); correction ba475ab declared `httpx2>=2.0` in requirements. Targeted validator rejected it assuming httpx2 does not exist — false: PyPI lists httpx2 2.0.0–2.16.0, required by anthropic and google-genai; 63 tests pass. Review stopped `native_stop_required` (escalated, terminal). No further review action; delivery follows ordinary policy.
- T4 done: app.py + README + 4 AppTest tests; 67 tests pass (parent re-ran). `.env.example` still missing (README references it).

## Next step

T5: user creates .env.example/.env with free Gemini key, runs `streamlit run app.py`; then secret scan before push.
