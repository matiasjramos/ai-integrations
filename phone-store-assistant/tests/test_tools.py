import pytest

from phone_store_assistant.leads import SqliteLeadRepository
from phone_store_assistant.models import Product
from phone_store_assistant.tools import TOOL_SPECS, ToolExecutor

PRODUCTS = [
    Product("A", "Samsung", "A15", 128, 200000, 5),
    Product("B", "Samsung", "S24", 256, 900000, 0),
    Product("C", "Apple", "iPhone 15", 128, 1200000, 2),
]


class FakeCatalog:
    def __init__(self, products=PRODUCTS, error=None):
        self.products, self.error = products, error

    def list_products(self):
        if self.error:
            raise self.error
        return self.products


class SpyNotifier:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def notify_lead(self, lead, product):
        if self.error:
            raise self.error
        self.calls.append((lead, product))


def make(catalog=None, notifier=None):
    leads = SqliteLeadRepository(":memory:")
    notifier = notifier or SpyNotifier()
    return ToolExecutor(catalog or FakeCatalog(), leads, notifier), leads, notifier


def test_spec_schemas_are_strict_and_consistent():
    assert [s.name for s in TOOL_SPECS] == ["search_products", "check_stock", "create_lead"]
    for spec in TOOL_SPECS:
        schema = spec.input_schema
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
    search = TOOL_SPECS[0].input_schema
    assert search["required"] == []
    assert "ONLY" in TOOL_SPECS[2].description


def test_search_filters_and_hides_stock_counts():
    ex, _, _ = make()
    res = ex.execute("search_products", {"brand": "samsung", "max_price": 500000})
    assert not res.is_error
    [p] = res.content["products"]
    assert p == {"id": "A", "brand": "Samsung", "model": "A15", "storage_gb": 128,
                 "price_ars": 200000, "in_stock": True}
    assert "stock" not in p and "units" not in p


def test_search_without_filters_and_limit_of_10():
    many = [Product(f"P{i}", "X", "m", 64, 1000, 1) for i in range(15)]
    ex, _, _ = make(FakeCatalog(many))
    assert len(ex.execute("search_products", {}).content["products"]) == 10


def test_check_stock():
    ex, _, _ = make()
    assert ex.execute("check_stock", {"product_id": "A"}).content == {
        "id": "A", "in_stock": True, "units": 5}
    res = ex.execute("check_stock", {"product_id": "NOPE"})
    assert res.is_error and "unknown product_id" in res.content["error"]


def test_create_lead_unknown_product_saves_nothing():
    ex, leads, notifier = make()
    res = ex.execute("create_lead", {"name": "Ana", "contact": "x", "product_id": "NOPE",
                                     "intent_summary": "buy"})
    assert res.is_error
    assert leads.list_recent() == [] and notifier.calls == []


def test_create_lead_saves_and_notifies():
    ex, leads, notifier = make()
    res = ex.execute("create_lead", {"name": "Ana", "contact": "ana@x.com",
                                     "product_id": "A", "intent_summary": "buy"})
    assert res.content == {"lead_id": 1, "seller_notified": True}
    assert leads.list_recent()[0].name == "Ana"
    assert len(notifier.calls) == 1


def test_create_lead_notifier_failure_keeps_lead():
    ex, leads, _ = make(notifier=SpyNotifier(error=RuntimeError("down")))
    res = ex.execute("create_lead", {"name": "Ana", "contact": "x", "product_id": "A",
                                     "intent_summary": "buy"})
    assert not res.is_error
    assert res.content["seller_notified"] is False
    assert len(leads.list_recent()) == 1


@pytest.mark.parametrize("field", ["name", "contact"])
def test_create_lead_rejects_blank_fields(field):
    ex, leads, _ = make()
    args = {"name": "Ana", "contact": "x", "product_id": "A", "intent_summary": "buy"}
    args[field] = "   "
    assert ex.execute("create_lead", args).is_error
    assert leads.list_recent() == []


def test_catalog_failure_is_generic_error():
    ex, _, _ = make(FakeCatalog(error=RuntimeError("secret path /etc/x")))
    res = ex.execute("search_products", {})
    assert res.is_error
    assert "temporarily unavailable" in res.content["error"]
    assert "secret" not in str(res.content)


@pytest.mark.parametrize("name,args", [
    ("search_products", {"max_price": "cheap"}),
    ("search_products", {"max_price": True}),
    ("search_products", {"max_price": -1}),
    ("search_products", {"color": "red"}),
    ("check_stock", {}),
    ("check_stock", {"product_id": 7}),
    ("create_lead", {"name": "Ana"}),
    ("search_products", "not a dict"),
    ("drop_tables", {}),
])
def test_invalid_calls_are_errors(name, args):
    ex, _, _ = make()
    assert ex.execute(name, args).is_error
