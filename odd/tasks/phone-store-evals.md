# Feature: phone-store-evals

## Objective

Measure the phone-store assistant's behavior against the real model with a repeatable
set of scripted conversations, instead of manual spot checks.

## Problem / why

The assistant is probabilistic. Prompt or model changes (e.g. the off-topic scope rule,
Gemini model swaps) can silently break other behaviors. Unit tests use fake clients and
cannot catch model behavior. Evals give a pass rate per behavior category, so changes are
judged by numbers, not by one manual run.

## Scope

- In: eval harness (case format, isolated session per case, tool-call recording,
  deterministic checks, runner CLI with pacing and busy retries, summary report),
  initial dataset (~25 cases), unit tests for the harness, README section.
- Out: LLM-as-judge grading, CI integration, WhatsApp channel, human handoff, metrics
  dashboard (possible follow-ups).

## Constraints

- Free tier: pace requests (configurable delay), retry a case on "busy", and report
  infrastructure errors separately from quality failures.
- Each case is isolated: fresh session, in-memory SQLite, LogNotifier (never Telegram),
  bundled JSON catalog (deterministic data).
- Deterministic checks only (tool trace, lead state, reply text rules).
- No secrets read or printed; keys come from the env as today.
- Artifacts in English.

## Design

- `phone-store-assistant/evals/cases.json`: list of cases
  `{id, category, turns: [user msgs], checks: {...}}`.
- Checks: `tools_called`, `tools_not_called`, `lead_created` (bool),
  `lead_product_id`, `reply_contains_any`, `reply_not_contains`, `max_reply_chars`.
  Applied to the final state after all turns (tool trace spans all turns; reply checks
  use the last reply).
- `RecordingExecutor` wraps `ToolExecutor` and records `(name, args, is_error)`.
- `python -m evals.run [--provider] [--delay] [--case ID] [--category C]` prints per-case
  PASS/FAIL/ERROR with failed check reasons and a per-category pass rate; exit code 1 on
  any FAIL.
- Categories: catalog_search, stock, not_in_catalog, off_topic, prompt_injection,
  lead_complete, lead_missing_info, browsing_no_lead.

## Tasks

- [x] E1 Harness + unit tests (fake session; no network) — route: delegated writer
      (2+ non-trivial files).
- [x] E2 Initial dataset (~25 cases over all categories) — same writer.
- [x] E3 README "Evaluation" section; user runs the evals once with his key and the
      baseline pass rate is recorded here.

## Acceptance criteria

- `pytest` passes (existing 76 + new harness tests) with no network.
- `python -m evals.run` runs end to end against Gemini and prints a per-category report.
- Busy/503 after retries is reported as ERROR, not FAIL.

## Checks

- TDD: off (project default, not configured). Runner: `.venv/Scripts/python -m pytest -q`
  from `phone-store-assistant/`.

## Progress

- Created after phone-store-assistant T5 manual runs (branch `feat/phone-store-assistant`,
  base 6329749).
- E1 done: commit f443e81 (harness, runner, tests); suite 101 passed (76 + 25 new).
- E2 done: 28 cases in 8 categories (4/4/3/3/4/4/3/3); suite 102 passed. Commit: see git log (`add initial eval cases`).

- Slice review a27f405..3cfd653 (lens review-reliability): approved, acknowledged (authority burned). Non-blocking follow-ups: test that the busy predicate matches the real session message; test `run.main` (filters, exit codes, provider override); cooldown test for a single-model session; review cases.json text checks after the first real run.

- E3 done: README "Evaluation" section. Baseline run by user (2026-11-19, Gemini free tier, mostly gemini-3.5-flash-lite after 429/503 on primary): 28/28 PASS, 0 ERROR. One busy 429 on the fallback was retried and passed.

## Next step

Feature done. Review follow-ups addressed in phone-store-assistant T6 (f1b920d transient flag, 2c2e343 run.main + single-model cooldown tests; cases.json text checks held on the first real run). Optional: add harder cases (the 100% baseline suggests the set is still easy).
