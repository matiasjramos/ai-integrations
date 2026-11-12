"""Seller notification port with Telegram and log-only adapters."""

import logging
from typing import Protocol

import httpx

from .config import Settings
from .models import Lead, Product

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """The seller could not be notified."""


class Notifier(Protocol):
    def notify_lead(self, lead: Lead, product: Product) -> None: ...


def format_lead_message(lead: Lead, product: Product) -> str:
    return (
        "New lead\n"
        f"Name: {lead.name}\n"
        f"Contact: {lead.contact}\n"
        f"Product: {product.brand} {product.model} {product.storage_gb}GB "
        f"(ARS {product.price_ars})\n"
        f"Intent: {lead.intent_summary}"
    )


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, client: httpx.Client | None = None):
        self._token = bot_token
        self._chat_id = chat_id
        self._client = client or httpx.Client(timeout=5.0)

    def notify_lead(self, lead: Lead, product: Product) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": format_lead_message(lead, product)}
        try:
            response = self._client.post(url, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # `from None`: the original exception message embeds the URL (and the token).
            raise NotificationError(
                f"Telegram returned HTTP {exc.response.status_code}"
            ) from None
        except httpx.HTTPError as exc:
            raise NotificationError(f"Telegram request failed: {type(exc).__name__}") from None


class LogNotifier:
    def notify_lead(self, lead: Lead, product: Product) -> None:
        logger.info("Lead notification (no Telegram configured):\n%s",
                    format_lead_message(lead, product))


def build_notifier(config: Settings) -> Notifier:
    if config.telegram_bot_token and config.telegram_chat_id:
        return TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
    return LogNotifier()
