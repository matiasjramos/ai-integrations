"""Catalog port and adapters (JSON, Google Sheets, fallback) plus pure query helpers."""

import json
import logging
from pathlib import Path
from typing import Protocol

from .config import Settings
from .models import Product

logger = logging.getLogger(__name__)

_INT_FIELDS = ("storage_gb", "price_ars", "stock")
_STR_FIELDS = ("id", "brand", "model")


class CatalogError(Exception):
    """Catalog data could not be read or is malformed."""


class CatalogRepository(Protocol):
    def list_products(self) -> list[Product]: ...


def _to_product(row: dict, index: int) -> Product:
    """Validate one raw row. Sheets returns numbers as str/float/int depending on cell format."""
    try:
        values = {f: str(row[f]).strip() for f in _STR_FIELDS}
        values.update({f: int(float(str(row[f]).replace(",", "").strip())) for f in _INT_FIELDS})
    except (KeyError, ValueError) as exc:
        raise CatalogError(f"Malformed catalog row {index}: {exc!r}") from exc
    if not values["id"]:
        raise CatalogError(f"Malformed catalog row {index}: empty id")
    return Product(**values)


class JsonCatalog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def list_products(self) -> list[Product]:
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogError(f"Cannot read catalog {self.path}: {exc}") from exc
        return [_to_product(r, i) for i, r in enumerate(rows)]


class SheetsCatalog:
    def __init__(self, service_account_file: str, sheet_id: str, worksheet: str = "catalog"):
        self.service_account_file = service_account_file
        self.sheet_id = sheet_id
        self.worksheet = worksheet

    def list_products(self) -> list[Product]:
        # Lazy import: JSON-only runs and tests don't need gspread configured.
        import gspread

        client = gspread.service_account(filename=self.service_account_file)
        ws = client.open_by_key(self.sheet_id).worksheet(self.worksheet)
        return [_to_product(r, i) for i, r in enumerate(ws.get_all_records())]


class FallbackCatalog:
    """Use the primary source; on any failure serve the fallback so the bot stays up."""

    def __init__(self, primary: CatalogRepository, fallback: CatalogRepository):
        self.primary = primary
        self.fallback = fallback
        self.last_source: str | None = None

    def list_products(self) -> list[Product]:
        try:
            products = self.primary.list_products()
            self.last_source = "primary"
            return products
        except Exception as exc:  # any primary failure must degrade, not crash
            logger.warning("Primary catalog failed (%s); using fallback", type(exc).__name__)
            self.last_source = "fallback"
            return self.fallback.list_products()


def search_products(
    products: list[Product],
    brand: str | None = None,
    max_price: int | None = None,
    storage_gb: int | None = None,
) -> list[Product]:
    result = products
    if brand:
        result = [p for p in result if p.brand.lower() == brand.strip().lower()]
    if max_price is not None:
        result = [p for p in result if p.price_ars <= max_price]
    if storage_gb is not None:
        result = [p for p in result if p.storage_gb == storage_gb]
    return list(result)


def find_product(products: list[Product], product_id: str) -> Product | None:
    return next((p for p in products if p.id == product_id), None)


def build_catalog(config: Settings) -> CatalogRepository:
    json_catalog = JsonCatalog(config.catalog_json_path)
    if config.google_service_account_file and config.google_sheet_id:
        sheets = SheetsCatalog(
            config.google_service_account_file,
            config.google_sheet_id,
            config.google_sheet_worksheet,
        )
        return FallbackCatalog(sheets, json_catalog)
    return json_catalog
