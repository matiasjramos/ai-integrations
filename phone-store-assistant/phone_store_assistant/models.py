"""Domain models. Frozen so tools and repositories can't mutate shared state."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Product:
    id: str
    brand: str
    model: str
    storage_gb: int
    price_ars: int
    stock: int

    @property
    def in_stock(self) -> bool:
        return self.stock > 0


@dataclass(frozen=True)
class Lead:
    name: str
    contact: str
    product_id: str
    intent_summary: str
    created_at: datetime | None = None
    id: int | None = None
