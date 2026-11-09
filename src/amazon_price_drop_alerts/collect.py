"""Fetch the current price of each watchlist item from the ScrapeUnblocker Amazon product API.

One API request per item per run. The SDK already retries 429/502/503/504 responses; on
top of that a product that is still blocked or timed out gets one more try after a pause.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from scrapeunblocker.exceptions import (
    AuthenticationError,
    BlockedError,
    BrowserTimeoutError,
    PaymentRequiredError,
    RateLimitError,
    ScrapeTimeoutError,
    ScrapeUnblockerError,
    ServerError,
    UpstreamOutageError,
)
from scrapeunblocker.exceptions import ConnectionError as SUConnectionError

from .config import WatchItem

log = logging.getLogger(__name__)

RETRYABLE = (
    BlockedError,
    BrowserTimeoutError,
    RateLimitError,
    ScrapeTimeoutError,
    ServerError,
    SUConnectionError,
    UpstreamOutageError,
)
# Errors that will fail for every item alike: stop the run instead of burning retries.
FATAL = (AuthenticationError, PaymentRequiredError)


class ProductClient(Protocol):
    """The slice of ``scrapeunblocker.Client`` this package uses."""

    def amazon_product(self, *, asin: str, marketplace: str) -> Any: ...


@dataclass(frozen=True)
class Observation:
    """What one product looked like on this run."""

    key: str
    asin: str
    marketplace: str
    title: str
    url: str
    price: float | None
    currency: str | None
    list_price: float | None = None
    in_stock: bool | None = None
    rating: float | None = None
    review_count: int | None = None
    offers_count: int | None = None
    offers_from_price: float | None = None
    image: str | None = None

    @property
    def available(self) -> bool:
        """True when Amazon shows a buy-box price. No price means unavailable."""
        return self.price is not None and self.in_stock is not False


@dataclass
class CollectResult:
    observations: list[Observation] = field(default_factory=list)
    failures: list[tuple[WatchItem, str]] = field(default_factory=list)


def shape(item: WatchItem, raw: Any) -> Observation:
    """Keep the fields the alerts use from an Amazon product API response."""
    if not isinstance(raw, dict):
        raise ScrapeUnblockerError(f"unexpected response for {item.key}: {type(raw).__name__}")
    title = item.name or _text(raw.get("title")) or item.asin
    return Observation(
        key=item.key,
        asin=item.asin,
        marketplace=item.marketplace,
        title=title,
        url=_text(raw.get("url")) or item.product_url,
        price=_number(raw.get("price")),
        currency=_text(raw.get("currency")),
        list_price=_number(raw.get("listPrice")),
        in_stock=raw.get("inStock") if isinstance(raw.get("inStock"), bool) else None,
        rating=_number(raw.get("rating")),
        review_count=_integer(raw.get("reviewCount")),
        offers_count=_integer(raw.get("offersCount")),
        offers_from_price=_number(raw.get("offersFromPrice")),
        image=_text(raw.get("image")),
    )


def fetch(
    client: ProductClient,
    item: WatchItem,
    *,
    attempts: int = 2,
    pause: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Observation:
    """Fetch one product, retrying transient blocks and timeouts."""
    for attempt in range(1, attempts + 1):
        try:
            raw = client.amazon_product(asin=item.asin, marketplace=item.marketplace)
        except RETRYABLE as exc:
            if attempt == attempts:
                raise
            log.warning("%s: %s, retrying in %.0fs", item.key, type(exc).__name__, pause)
            sleep(pause)
            continue
        return shape(item, raw)
    raise AssertionError("unreachable")


def collect(
    client: ProductClient,
    items: Iterable[WatchItem],
    *,
    attempts: int = 2,
    pause: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectResult:
    """Fetch every item. A failed item is reported and skipped; its state stays as it was."""
    result = CollectResult()
    for item in items:
        try:
            obs = fetch(client, item, attempts=attempts, pause=pause, sleep=sleep)
        except FATAL:
            raise
        except ScrapeUnblockerError as exc:
            log.warning("%s: %s: %s", item.key, type(exc).__name__, exc)
            result.failures.append((item, f"{type(exc).__name__}: {exc}"))
            continue
        result.observations.append(obs)
    return result


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
