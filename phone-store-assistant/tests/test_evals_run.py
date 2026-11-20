import dataclasses

import pytest

from evals import run as run_mod
from evals.harness import ERROR, FAIL, PASS, Case, CaseResult


def _case(cid, category):
    return Case(cid, category, ("hi",), {"lead_created": False})


@pytest.fixture
def runner(monkeypatch):
    """Patch settings, cases and run_case so main() never touches a provider."""
    state = {"cases": [_case("a1", "alpha"), _case("a2", "alpha"), _case("b1", "beta")],
             "status": {}, "ran": [], "sleeps": [], "providers": []}

    @dataclasses.dataclass(frozen=True)
    class Settings:
        llm_provider: str = "gemini"
        catalog_json_path: str = "unused"

    monkeypatch.setattr(run_mod, "load_settings", lambda: Settings())
    monkeypatch.setattr(run_mod, "load_cases", lambda path: state["cases"])
    monkeypatch.setattr(run_mod.time, "sleep", state["sleeps"].append)

    def fake_create(settings, executor):
        state["providers"].append(settings.llm_provider)

    monkeypatch.setattr(run_mod, "create_chat_session", fake_create)

    def fake_run_case(case, factory, catalog_path, retries):
        factory(None)  # exercises the session factory with the (overridden) settings
        state["ran"].append((case.id, retries))
        return CaseResult(case, state["status"].get(case.id, PASS))

    monkeypatch.setattr(run_mod, "run_case", fake_run_case)
    return state


def test_runs_all_cases_exit_zero(runner):
    assert run_mod.main([]) == 0
    assert [c for c, _ in runner["ran"]] == ["a1", "a2", "b1"]


def test_case_filter(runner):
    assert run_mod.main(["--case", "b1"]) == 0
    assert [c for c, _ in runner["ran"]] == ["b1"]


def test_category_filter(runner):
    run_mod.main(["--category", "alpha"])
    assert [c for c, _ in runner["ran"]] == ["a1", "a2"]


def test_no_match_exits_2_without_running(runner, capsys):
    assert run_mod.main(["--case", "nope"]) == 2
    assert runner["ran"] == []
    assert "No cases match" in capsys.readouterr().out


def test_fail_exits_1_but_error_does_not(runner):
    runner["status"] = {"a2": ERROR}
    assert run_mod.main([]) == 0
    runner["status"] = {"a2": FAIL}
    assert run_mod.main([]) == 1


def test_provider_override_and_retries_forwarded(runner):
    run_mod.main(["--provider", "claude", "--retries", "5", "--case", "a1"])
    assert runner["providers"] == ["claude"]
    assert runner["ran"] == [("a1", 5)]


def test_delay_between_cases_only(runner):
    run_mod.main(["--delay", "2.5"])
    assert runner["sleeps"] == [2.5, 2.5]  # 3 cases -> 2 gaps, none before the first
