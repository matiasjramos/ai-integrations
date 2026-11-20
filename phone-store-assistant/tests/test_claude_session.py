import json
from types import SimpleNamespace as NS

import anthropic
import httpx2
import pytest

from phone_store_assistant.chat import ChatError
from phone_store_assistant.claude_session import ClaudeChatSession
from phone_store_assistant.models import Product
from phone_store_assistant.leads import SqliteLeadRepository
from phone_store_assistant.notifier import LogNotifier
from phone_store_assistant.tools import ToolExecutor

PRODUCTS = [Product("A", "Samsung", "A15", 128, 200000, 5)]


class Catalog:
    def list_products(self):
        return PRODUCTS


def text(t):
    return NS(type="text", text=t)


def tool_use(id_, name, input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


def resp(content, stop_reason, usage=None):
    return NS(content=content, stop_reason=stop_reason,
              usage=usage or NS(input_tokens=10, output_tokens=5,
                                cache_read_input_tokens=3, cache_creation_input_tokens=0))


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        # Snapshot history length: the session mutates the same list afterwards.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def session(script, max_iterations=6):
    executor = ToolExecutor(Catalog(), SqliteLeadRepository(":memory:"), LogNotifier())
    client = FakeClient(script)
    return ClaudeChatSession(client, "claude-opus-5-5", "medium", executor,
                             max_iterations), client


def test_tool_loop_sends_all_results_in_one_message():
    s, client = session([
        resp([text("let me look"), tool_use("t1", "search_products", {"brand": "Samsung"}),
              tool_use("t2", "check_stock", {"product_id": "A"})], "tool_use"),
        resp([text("Tenemos el A15")], "end_turn"),
    ])
    assert s.send("hola") == "Tenemos el A15"
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    results = second[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert all(r["type"] == "tool_result" and r["is_error"] is False for r in results)
    assert json.loads(results[1]["content"])["units"] == 5
    assert second[1]["content"] is not None  # assistant content passed back


def test_request_parameters():
    s, client = session([resp([text("hi")], "end_turn")])
    s.send("hola")
    kwargs = client.calls[0]
    assert kwargs["output_config"] == {"effort": "medium"}
    assert kwargs["cache_control"] == {"type": "ephemeral"}
    assert kwargs["max_tokens"] == 16000
    assert all(t["strict"] is True for t in kwargs["tools"])
    assert len(kwargs["tools"]) == 3
    for forbidden in ("thinking", "tool_choice", "temperature", "top_p"):
        assert forbidden not in kwargs


def test_tool_error_is_flagged():
    s, client = session([
        resp([tool_use("t1", "check_stock", {"product_id": "NOPE"})], "tool_use"),
        resp([text("no existe")], "end_turn"),
    ])
    s.send("x")
    assert client.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_refusal_and_max_tokens_and_pause_turn():
    s, _ = session([resp([], "refusal")])
    assert "can't help" in s.send("x")
    s, _ = session([resp([text("partial")], "max_tokens")])
    assert s.send("x").startswith("partial")
    s, _ = session([resp([], "pause_turn"), resp([text("done")], "end_turn")])
    assert s.send("x") == "done"


def test_max_iterations_stops_loop():
    looping = [resp([tool_use(f"t{i}", "search_products", {})], "tool_use")
               for i in range(5)]
    s, client = session(looping, max_iterations=3)
    assert "couldn't complete" in s.send("x")
    assert len(client.calls) == 3


def test_usage_accumulates():
    s, _ = session([resp([tool_use("t", "search_products", {})], "tool_use"),
                    resp([text("ok")], "end_turn")])
    s.send("x")
    assert s.usage["input_tokens"] == 20
    assert s.usage["cache_read_input_tokens"] == 6


def _api_status_error(cls, status):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(status, request=request), body=None)


@pytest.mark.parametrize("exc", [
    _api_status_error(anthropic.RateLimitError, 429),
    _api_status_error(anthropic.AuthenticationError, 401),
    _api_status_error(anthropic.InternalServerError, 500),
    anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")),
])
def test_api_errors_become_chat_error_and_roll_back(exc):
    s, client = session([resp([text("first")], "end_turn"), exc,
                         resp([text("recovered")], "end_turn")])
    s.send("one")
    before = len(s._history)
    with pytest.raises(ChatError):
        s.send("two")
    assert len(s._history) == before
    assert s.send("three") == "recovered"
    assert [m["content"] for m in client.calls[2]["messages"] if m["role"] == "user"] == [
        "one", "three"]


def test_rate_limit_is_transient_others_are_not():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    for exc, transient in [
        (_api_status_error(anthropic.RateLimitError, 429), True),
        (_api_status_error(anthropic.InternalServerError, 500), False),
        (anthropic.APIConnectionError(request=request), False),
    ]:
        s, _ = session([exc])
        with pytest.raises(ChatError) as info:
            s.send("x")
        assert info.value.transient is transient
