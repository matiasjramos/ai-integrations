import json

import pytest

from evals.harness import (
    ERROR, FAIL, PASS, CaseError, RecordingExecutor, load_cases, parse_case, run_case,
)
from evals.run import summarize
from phone_store_assistant.catalog import JsonCatalog
from phone_store_assistant.chat import ChatError
from phone_store_assistant.config import PROJECT_DIR
from phone_store_assistant.tools import ToolExecutor

CATALOG = PROJECT_DIR / "data" / "catalog.json"


class ScriptedSession:
    """Fake session: each step is a reply, an exception, or a function (executor) -> reply."""

    def __init__(self, executor, steps):
        self.executor, self.steps = executor, list(steps)

    def send(self, text):
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(self.executor) if callable(step) else step


def case(checks, turns=("hola",), category="c", cid="x"):
    return parse_case({"id": cid, "category": category, "turns": list(turns),
                       "checks": checks})


def run(c, steps, **kw):
    return run_case(c, lambda ex: ScriptedSession(ex, steps), CATALOG,
                    sleep=lambda s: None, **kw)


def search(ex):
    ex.execute("search_products", {"brand": "Samsung"})
    return "Tengo Samsung"


def lead(ex):
    ex.execute("create_lead", {"name": "Ana", "contact": "1155", "product_id": "SAM-A15-128",
                               "intent_summary": "quiere comprar"})
    return "Listo, te contactan"


def test_tools_called_pass_and_fail():
    c = case({"tools_called": ["search_products"]})
    assert run(c, [search]).status == PASS
    result = run(c, ["sin tools"])
    assert result.status == FAIL and "search_products" in result.reasons[0]


def test_tools_not_called():
    c = case({"tools_not_called": ["create_lead"]})
    assert run(c, ["hola"]).status == PASS
    assert run(c, [lead]).status == FAIL


def test_lead_created_true_and_false():
    assert run(case({"lead_created": True}), [lead]).status == PASS
    assert run(case({"lead_created": True}), ["no"]).status == FAIL
    assert run(case({"lead_created": False}), ["no"]).status == PASS
    assert run(case({"lead_created": False}), [lead]).status == FAIL


def test_lead_product_id():
    assert run(case({"lead_product_id": "SAM-A15-128"}), [lead]).status == PASS
    assert run(case({"lead_product_id": "MOT-G24-128"}), [lead]).status == FAIL


def test_rejected_lead_call_is_not_a_lead():
    # The executor rejects unknown products, so nothing is saved.
    def bad(ex):
        ex.execute("create_lead", {"name": "A", "contact": "1", "product_id": "NOPE",
                                   "intent_summary": "x"})
        return "ok"
    assert run(case({"lead_created": False}), [bad]).status == PASS


def test_reply_contains_any_is_case_insensitive():
    c = case({"reply_contains_any": ["SAMSUNG", "motorola"]})
    assert run(c, ["Te recomiendo un samsung"]).status == PASS
    assert run(c, ["nada"]).status == FAIL


def test_reply_not_contains_is_case_insensitive():
    c = case({"reply_not_contains": ["Receta"]})
    assert run(c, ["Solo celulares"]).status == PASS
    assert run(c, ["Esta RECETA es"]).status == FAIL


def test_max_reply_chars():
    c = case({"max_reply_chars": 10})
    assert run(c, ["corto"]).status == PASS
    result = run(c, ["x" * 11])
    assert result.status == FAIL and "too long" in result.reasons[0]


def test_multi_turn_uses_last_reply_but_all_tool_calls():
    c = case({"tools_called": ["search_products", "create_lead"],
              "reply_not_contains": ["Tengo Samsung"]},
             turns=("busco samsung", "quiero comprar"))
    result = run(c, [search, lead])
    assert result.status == PASS
    assert result.tools == ["search_products", "create_lead"]
    assert result.reply == "Listo, te contactan"


def test_all_failed_checks_are_reported():
    c = case({"tools_called": ["check_stock"], "lead_created": True})
    assert len(run(c, ["nada"]).reasons) == 2


def test_chat_error_is_error_not_fail():
    result = run(case({"lead_created": False}), [ChatError("provider exploded")])
    assert result.status == ERROR and "exploded" in result.reasons[0]


def test_busy_retries_whole_case_then_passes():
    sleeps, built = [], []

    def factory(ex):
        built.append(ex)
        steps = [ChatError("The model is busy")] if len(built) == 1 else ["hola"]
        return ScriptedSession(ex, steps)

    result = run_case(case({"lead_created": False}), factory, CATALOG, retries=2,
                      retry_wait=7, sleep=sleeps.append)
    assert result.status == PASS and sleeps == [7]
    assert built[0] is not built[1]  # fresh state per attempt


def test_busy_exhausts_retries_to_error():
    sleeps = []
    result = run_case(
        case({"lead_created": False}),
        lambda ex: ScriptedSession(ex, [ChatError("busy")]),
        CATALOG, retries=2, retry_wait=1, sleep=sleeps.append,
    )
    assert result.status == ERROR and len(sleeps) == 2


def test_non_busy_error_does_not_retry():
    sleeps = []
    result = run_case(case({"lead_created": False}),
                      lambda ex: ScriptedSession(ex, [ChatError("bad key")]),
                      CATALOG, sleep=sleeps.append)
    assert result.status == ERROR and sleeps == []


def test_recording_executor_records_calls_and_errors():
    ex = RecordingExecutor(ToolExecutor(JsonCatalog(CATALOG), None, None))
    ok = ex.execute("check_stock", {"product_id": "SAM-A15-128"})
    bad = ex.execute("check_stock", {"product_id": "NOPE"})
    assert not ok.is_error and bad.is_error
    assert [(c.name, c.is_error) for c in ex.calls] == [("check_stock", False),
                                                        ("check_stock", True)]


@pytest.mark.parametrize("raw", [
    {"id": "a", "category": "c", "turns": ["x"], "checks": {"bogus": 1}},
    {"id": "a", "category": "c", "turns": [], "checks": {"lead_created": True}},
    {"id": "a", "category": "c", "turns": ["x"], "checks": {}},
    {"id": "a", "turns": ["x"], "checks": {"lead_created": True}},
    {"id": "a", "category": "c", "turns": ["x"], "checks": {"lead_created": "yes"}},
    {"id": "a", "category": "c", "turns": ["x"], "checks": {"tools_called": "search"}},
    {"id": "a", "category": "c", "turns": ["x"], "checks": {"max_reply_chars": 0}},
])
def test_invalid_cases_rejected(raw):
    with pytest.raises(CaseError):
        parse_case(raw)


def test_unknown_check_message_names_key():
    with pytest.raises(CaseError, match="bogus"):
        parse_case({"id": "a", "category": "c", "turns": ["x"], "checks": {"bogus": 1}})


def test_duplicate_ids_rejected(tmp_path):
    one = {"id": "a", "category": "c", "turns": ["x"], "checks": {"lead_created": False}}
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([one, one]), encoding="utf-8")
    with pytest.raises(CaseError, match="duplicate"):
        load_cases(path)


def test_summary_excludes_errors_from_rate():
    results = [run(case({"lead_created": False}, category="a", cid="1"), ["ok"]),
               run(case({"lead_created": True}, category="a", cid="2"), ["no"]),
               run(case({"lead_created": False}, category="a", cid="3"),
                   [ChatError("x")])]
    lines, passed, failed, errors = summarize(results)
    assert (passed, failed, errors) == (1, 1, 1)
    assert "50%" in lines[1]


def test_bundled_dataset_is_valid_and_covers_every_category():
    cases = load_cases(PROJECT_DIR / "evals" / "cases.json")
    assert {c.category for c in cases} == {
        "catalog_search", "stock", "not_in_catalog", "off_topic", "prompt_injection",
        "lead_complete", "lead_missing_info", "browsing_no_lead",
    }
