from types import SimpleNamespace as NS

import pytest
from google.genai import errors, types

from phone_store_assistant.chat import ChatError
from phone_store_assistant.gemini_session import GeminiChatSession
from phone_store_assistant.leads import SqliteLeadRepository
from phone_store_assistant.models import Product
from phone_store_assistant.notifier import LogNotifier
from phone_store_assistant.tools import ToolExecutor

PRODUCTS = [Product("A", "Samsung", "A15", 128, 200000, 5)]


class Catalog:
    def list_products(self):
        return PRODUCTS


def reply(parts, calls=None, text=None):
    content = types.Content(role="model", parts=parts)
    return NS(candidates=[NS(content=content)], function_calls=calls, text=text,
              usage_metadata=NS(prompt_token_count=10, candidates_token_count=4))


def call_reply(*calls):
    parts = [types.Part.from_function_call(name=n, args=a) for n, a in calls]
    return reply(parts, calls=[p.function_call for p in parts])


def text_reply(t):
    return reply([types.Part.from_text(text=t)], text=t)


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append({**kwargs, "contents": list(kwargs["contents"])})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def session(script, max_iterations=6, fallback_model=None):
    executor = ToolExecutor(Catalog(), SqliteLeadRepository(":memory:"), LogNotifier())
    client = FakeClient(script)
    return GeminiChatSession(client, "gemini-3.8-flash", executor, max_iterations,
                             fallback_model=fallback_model), client


def test_function_call_loop_and_config():
    s, client = session([
        call_reply(("search_products", {"brand": "Samsung"}),
                   ("check_stock", {"product_id": "A"})),
        text_reply("Tenemos el A15"),
    ])
    assert s.send("hola") == "Tenemos el A15"
    first = client.calls[0]
    cfg = first["config"]
    assert cfg.automatic_function_calling.disable is True
    declarations = cfg.tools[0].function_declarations
    assert [d.name for d in declarations] == ["search_products", "check_stock", "create_lead"]
    assert all("additionalProperties" not in d.parameters_json_schema for d in declarations)
    contents = client.calls[1]["contents"]
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert {c.role for c in contents} <= {"user", "model"}  # API rejects any other role
    responses = [p.function_response for p in contents[2].parts]
    assert [r.name for r in responses] == ["search_products", "check_stock"]
    assert "result" in responses[0].response
    assert s.usage == {"input_tokens": 20, "output_tokens": 8}


def test_tool_error_is_sent_as_error_payload():
    s, client = session([call_reply(("check_stock", {"product_id": "NOPE"})),
                         text_reply("no existe")])
    s.send("x")
    response = client.calls[1]["contents"][2].parts[0].function_response.response
    assert "error" in response


def test_missing_candidates_gives_safe_message():
    s, _ = session([NS(candidates=None, function_calls=None, text=None,
                       usage_metadata=None)])
    assert "couldn't generate" in s.send("x")


def test_max_iterations_stops_loop():
    s, client = session([call_reply(("search_products", {})) for _ in range(5)],
                        max_iterations=2)
    assert "couldn't complete" in s.send("x")
    assert len(client.calls) == 2


def test_api_error_becomes_chat_error_and_rolls_back():
    err = errors.APIError(500, {"error": {"message": "boom"}})
    s, client = session([text_reply("first"), err, text_reply("recovered")])
    s.send("one")
    before = len(s._history)
    with pytest.raises(ChatError):
        s.send("two")
    assert len(s._history) == before
    assert s.send("three") == "recovered"
    users = [c.parts[0].text for c in client.calls[2]["contents"] if c.role == "user"]
    assert users == ["one", "three"]


@pytest.mark.parametrize(
    ("code", "expected"),
    [(404, "GEMINI_MODEL"), (403, "GEMINI_API_KEY"), (429, "busy"), (500, "had a problem")],
)
def test_api_error_message_depends_on_status(code, expected):
    s, _ = session([errors.APIError(code, {"error": {"message": "x"}})])
    with pytest.raises(ChatError, match=expected):
        s.send("hi")


def overloaded():
    return errors.APIError(503, {"error": {"message": "high demand", "status": "UNAVAILABLE"}})


def test_overloaded_primary_falls_back_to_secondary_model():
    s, client = session([overloaded(), text_reply("hola!")], fallback_model="gemini-2.5-flash")
    assert s.send("hola") == "hola!"
    assert [c["model"] for c in client.calls] == ["gemini-3.8-flash", "gemini-2.5-flash"]
    assert s.last_model == "gemini-2.5-flash"


def test_both_models_overloaded_gives_busy_message_and_rolls_back():
    s, _ = session([overloaded(), overloaded()], fallback_model="gemini-2.5-flash")
    with pytest.raises(ChatError, match="busy"):
        s.send("hola")
    assert s._history == []


def test_config_errors_do_not_trigger_fallback():
    s, client = session([errors.APIError(404, {"error": {"message": "x"}})],
                        fallback_model="gemini-2.5-flash")
    with pytest.raises(ChatError, match="GEMINI_MODEL"):
        s.send("hola")
    assert len(client.calls) == 1
