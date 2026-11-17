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
- T4 done: app.py + README + 4 AppTest tests; 67 tests pass (parent re-ran). `.env.example` still missing (README references it). T4 review assess: medium, under_budget (293 lines) → pending in slice from ba475ab.
- T5 run 1: Gemini 404 — default alias `gemini-flash-latest` not available. User listed models with own key; default → `gemini-3.8-flash`. Gemini errors now mapped: 404 → check GEMINI_MODEL, 401/403 → check key, 429 → busy. 71 tests pass.
- T5 run 2: gemini-3.8-flash 503 UNAVAILABLE ("high demand"). Added fallback model (GEMINI_FALLBACK_MODEL, default gemini-2.5-flash) on 429/503 only; config errors never fall back. 74 tests pass.
- Slice review ba475ab..a27f405 (lineage review-848fbcfb268a892f): granted, approved + acknowledged. Follow-ups (non-blocking): sticky fallback within a turn; backoff/retry-after on 429; use getattr for exc.code in _generate; test factory fallback wiring + GEMINI_FALLBACK_MODEL default; guard sidebar leads query and session construction in app.py; orphan user message after ChatError; README references missing .env.example.
- T5 run 3: gemini-2.5-flash 404 "no longer available to new users" (listed but unusable). Probed with user key: 3.8/3.7 flash 503; 3.6-flash, 3.5-flash, 3.5-flash-lite, 3.1-flash-lite OK. Defaults → primary gemini-3.6-flash, fallback gemini-3.5-flash-lite (separate capacity). Fallback default now tested. 74 tests pass.
- T5 run 4: first tool call failed with 400 INVALID_ARGUMENT "Role 'tool' is not supported" on /v1. Function responses now go back with role `user`; test asserts only user/model roles. 74 tests pass.
- T5 run 5: tool calls work (stock query OK). Off-topic request (recipe) was answered. Added a scope section to SYSTEM_PROMPT: store topics only, one-sentence refusal, ignore role-change requests. Manual re-test OK (recipe refused in one line).
- T5 run 6: free tier returned 503 on both models; every call re-hit the failing primary first (extra latency). Added a 60s per-model cooldown after 429/503 (injectable clock); if all models are cooling down they are tried anyway. Also uses getattr for exc.code (review follow-up). 76 tests pass.

## Next step

T5: user creates .env.example/.env with free Gemini key, runs `streamlit run app.py`; then secret scan before push.
