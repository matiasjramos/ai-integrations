import sys
import types

import pytest

from phone_store_assistant import config
from phone_store_assistant.catalog import (
    CatalogError, FallbackCatalog, JsonCatalog, SheetsCatalog, build_catalog,
    find_product, search_products,
)
from phone_store_assistant.config import Settings, load_settings
from phone_store_assistant.models import Product


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)


@pytest.fixture
def json_path():
    return load_settings().catalog_json_path


@pytest.fixture
def products(json_path):
    return JsonCatalog(json_path).list_products()


class Boom:
    def list_products(self):
        raise RuntimeError("sheets down")


def test_json_catalog_loads(products):
    assert len(products) == 10
    assert isinstance(products[0], Product)
    assert isinstance(products[0].price_ars, int)


def test_json_catalog_missing_file(tmp_path):
    with pytest.raises(CatalogError):
        JsonCatalog(tmp_path / "nope.json").list_products()


def test_search_brand_case_insensitive(products):
    result = search_products(products, brand="sAmSuNg")
    assert result and all(p.brand == "Samsung" for p in result)


def test_search_filters(products):
    result = search_products(products, max_price=300000, storage_gb=128)
    assert result and all(p.price_ars <= 300000 and p.storage_gb == 128 for p in result)
    assert search_products(products, brand="Nokia") == []
    assert len(search_products(products)) == len(products)


def test_find_product(products):
    assert find_product(products, "SAM-A15-128").model == "Galaxy A15"
    assert find_product(products, "NOPE") is None


def test_fallback_uses_fallback_and_logs(json_path, caplog):
    cat = FallbackCatalog(Boom(), JsonCatalog(json_path))
    with caplog.at_level("WARNING"):
        assert len(cat.list_products()) == 10
    assert cat.last_source == "fallback"
    assert "Primary catalog failed" in caplog.text


def test_fallback_uses_primary_when_healthy(json_path):
    cat = FallbackCatalog(JsonCatalog(json_path), Boom())
    assert len(cat.list_products()) == 10
    assert cat.last_source == "primary"


def _fake_gspread(records):
    class WS:
        def get_all_records(self):
            return records

    class Book:
        def worksheet(self, name):
            assert name == "catalog"
            return WS()

    class Client:
        def open_by_key(self, key):
            assert key == "sheet-id"
            return Book()

    mod = types.ModuleType("gspread")
    mod.service_account = lambda filename: Client()
    return mod


def test_sheets_coerces_numeric_columns(monkeypatch):
    rows = [{"id": "X1", "brand": "Apple", "model": "iPhone", "storage_gb": "128",
             "price_ars": "1,299,999", "stock": 3.0}]
    monkeypatch.setitem(sys.modules, "gspread", _fake_gspread(rows))
    [p] = SheetsCatalog("sa.json", "sheet-id", "catalog").list_products()
    assert (p.storage_gb, p.price_ars, p.stock) == (128, 1299999, 3)


def test_sheets_malformed_row_raises(monkeypatch):
    rows = [{"id": "X1", "brand": "Apple", "model": "iPhone", "storage_gb": "abc",
             "price_ars": 1, "stock": 1}]
    monkeypatch.setitem(sys.modules, "gspread", _fake_gspread(rows))
    with pytest.raises(CatalogError):
        SheetsCatalog("sa.json", "sheet-id", "catalog").list_products()


def _settings(json_path, **over):
    base = dict(anthropic_model="m", effort="medium", google_service_account_file=None,
                google_sheet_id=None, google_sheet_worksheet="catalog",
                telegram_bot_token=None, telegram_chat_id=None, leads_db_path=":memory:",
                catalog_json_path=json_path)
    base.update(over)
    return Settings(**base)


def test_build_catalog_selection(json_path):
    assert isinstance(build_catalog(_settings(json_path)), JsonCatalog)
    both = build_catalog(
        _settings(json_path, google_service_account_file="sa.json", google_sheet_id="id")
    )
    assert isinstance(both, FallbackCatalog)
