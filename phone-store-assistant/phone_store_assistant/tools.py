"""Provider-neutral tools: specs (what the model sees) and an executor (what actually runs).

The model only proposes tool calls; this module validates and executes them, so
hallucinated ids or malformed arguments are rejected in code, not just in the prompt.
"""

import logging
from dataclasses import dataclass

from .catalog import CatalogRepository, find_product, search_products
from .leads import LeadRepository
from .models import Lead
from .notifier import Notifier

logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 10


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@dataclass(frozen=True)
class ToolResult:
    content: dict
    is_error: bool = False


def _schema(properties: dict, required: list[str]) -> dict:
    # Only the simple JSON-schema subset both providers accept.
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "search_products",
        "Search the phone catalog. All filters are optional; omit a filter to not apply it. "
        "Returns up to 10 matching products.",
        _schema(
            {
                "brand": {"type": "string", "description": "Brand name, e.g. Samsung"},
                "max_price": {"type": "integer", "minimum": 0,
                              "description": "Maximum price in ARS"},
                "storage_gb": {"type": "integer", "minimum": 1,
                               "description": "Exact storage size in GB"},
            },
            [],
        ),
    ),
    ToolSpec(
        "check_stock",
        "Check whether a product is in stock and how many units are available.",
        _schema(
            {"product_id": {"type": "string",
                            "description": "Product id returned by search_products"}},
            ["product_id"],
        ),
    ),
    ToolSpec(
        "create_lead",
        "Register a sales lead and notify a seller. Use ONLY for real buying intent: the "
        "customer wants to buy, reserve, or be contacted about a specific product AND has "
        "given their name and contact. Never use for casual browsing or price questions.",
        _schema(
            {
                "name": {"type": "string", "description": "Customer name"},
                "contact": {"type": "string", "description": "Customer phone or email"},
                "product_id": {"type": "string",
                               "description": "Product id returned by search_products"},
                "intent_summary": {"type": "string",
                                   "description": "One sentence on what the customer wants"},
            },
            ["name", "contact", "product_id", "intent_summary"],
        ),
    ),
)

_SPECS_BY_NAME = {s.name: s for s in TOOL_SPECS}
_TYPES = {"string": str, "integer": int}


def _error(message: str) -> ToolResult:
    return ToolResult({"error": message}, is_error=True)


def _validate(spec: ToolSpec, args: object) -> str | None:
    """Return an error message, or None. Gemini does not guarantee schema conformance."""
    if not isinstance(args, dict):
        return "arguments must be an object"
    props = spec.input_schema["properties"]
    unknown = set(args) - set(props)
    if unknown:
        return f"unknown arguments: {sorted(unknown)}"
    missing = [k for k in spec.input_schema["required"] if k not in args]
    if missing:
        return f"missing required arguments: {missing}"
    for key, value in args.items():
        expected = _TYPES[props[key]["type"]]
        # bool is an int subclass; reject it explicitly.
        if not isinstance(value, expected) or isinstance(value, bool):
            return f"argument '{key}' must be of type {props[key]['type']}"
        if "minimum" in props[key] and value < props[key]["minimum"]:
            return f"argument '{key}' must be >= {props[key]['minimum']}"
    return None


class ToolExecutor:
    def __init__(self, catalog: CatalogRepository, leads: LeadRepository, notifier: Notifier):
        self._catalog = catalog
        self._leads = leads
        self._notifier = notifier

    def execute(self, name: str, args: dict) -> ToolResult:
        spec = _SPECS_BY_NAME.get(name)
        if spec is None:
            return _error(f"unknown tool: {name}")
        problem = _validate(spec, args)
        if problem:
            return _error(problem)
        try:
            products = self._catalog.list_products()
        except Exception as exc:  # incl. FallbackCatalog when both sources fail
            logger.error("Catalog unavailable: %s", type(exc).__name__)
            return _error("catalog temporarily unavailable")
        return getattr(self, f"_{name}")(products, args)

    def _search_products(self, products, args) -> ToolResult:
        found = search_products(products, **args)[:MAX_SEARCH_RESULTS]
        return ToolResult({"products": [
            {"id": p.id, "brand": p.brand, "model": p.model, "storage_gb": p.storage_gb,
             "price_ars": p.price_ars, "in_stock": p.in_stock}
            for p in found
        ]})

    def _check_stock(self, products, args) -> ToolResult:
        product = find_product(products, args["product_id"])
        if product is None:
            return _error("unknown product_id")
        return ToolResult({"id": product.id, "in_stock": product.in_stock,
                           "units": product.stock})

    def _create_lead(self, products, args) -> ToolResult:
        product = find_product(products, args["product_id"])
        if product is None:  # hallucination guard: nothing is saved
            return _error("unknown product_id")
        name, contact = args["name"].strip(), args["contact"].strip()
        if not name or not contact:
            return _error("name and contact must not be empty")
        saved = self._leads.save(
            Lead(name, contact, product.id, args["intent_summary"].strip())
        )
        try:
            self._notifier.notify_lead(saved, product)
            notified = True
        except Exception as exc:  # the lead is safe in the DB; don't fail the conversation
            logger.warning("Seller notification failed: %s", type(exc).__name__)
            notified = False
        return ToolResult({"lead_id": saved.id, "seller_notified": notified})
