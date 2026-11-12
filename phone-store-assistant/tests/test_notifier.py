import json

import httpx
import pytest

from phone_store_assistant.models import Lead, Product
from phone_store_assistant.notifier import LogNotifier, NotificationError, TelegramNotifier

TOKEN = "123:SECRET-TOKEN"
LEAD = Lead("Ana", "ana@example.com", "P1", "Wants to buy")
PRODUCT = Product("P1", "Samsung", "Galaxy A15", 128, 289999, 5)


def _notifier(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TelegramNotifier(TOKEN, "42", client=client)


def test_posts_expected_url_and_payload():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    _notifier(handler).notify_lead(LEAD, PRODUCT)
    assert seen["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert seen["body"]["chat_id"] == "42"
    assert "Galaxy A15" in seen["body"]["text"] and "ana@example.com" in seen["body"]["text"]


def test_http_error_raises_without_token():
    with pytest.raises(NotificationError) as err:
        _notifier(lambda r: httpx.Response(500)).notify_lead(LEAD, PRODUCT)
    assert "500" in str(err.value)
    assert "SECRET-TOKEN" not in str(err.value)


def test_network_error_raises_without_token():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(NotificationError) as err:
        _notifier(handler).notify_lead(LEAD, PRODUCT)
    assert "SECRET-TOKEN" not in str(err.value)


def test_log_notifier_logs(caplog):
    with caplog.at_level("INFO"):
        LogNotifier().notify_lead(LEAD, PRODUCT)
    assert "Galaxy A15" in caplog.text
