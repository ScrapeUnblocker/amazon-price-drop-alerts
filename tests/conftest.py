"""Shared fakes: no test calls the ScrapeUnblocker API or a real webhook."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from amazon_price_drop_alerts.collect import Observation
from amazon_price_drop_alerts.config import Rules, WatchItem
from amazon_price_drop_alerts.process import Alert


def product_payload(asin: str = "B09XS7JWHH", price: float | None = 199.95, **extra: Any):
    """A trimmed Amazon product API response with the fields the package reads."""
    payload = {
        "asin": asin,
        "marketplace": "amazon.com",
        "url": f"https://www.amazon.com/dp/{asin}",
        "title": "Sony WH-1000XM5 Premium Noise Cancelling Wireless Headphones, Black",
        "brand": "Sony",
        "price": price,
        "currency": "USD" if price is not None else None,
        "priceRaw": f"${price:,.2f}" if price is not None else None,
        "listPrice": None,
        "availability": None,
        "inStock": None,
        "rating": 4.2,
        "reviewCount": 20334,
        "offersCount": 50,
        "offersFromPrice": 177.99,
        "image": "https://m.media-amazon.com/images/I/61O3iMlnJIL._AC_SL1500_.jpg",
        "exitCountry": "us",
    }
    payload.update(extra)
    return payload


class FakeClient:
    """Stands in for ``scrapeunblocker.Client``; answers from a dict keyed by ASIN."""

    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def amazon_product(self, *, asin: str, marketplace: str):
        self.calls.append((asin, marketplace))
        answer = self.responses[asin]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@dataclass
class FakeResponse:
    status_code: int = 200
    text: str = "ok"
    headers: dict[str, str] = field(default_factory=dict)


class RecordingHttp:
    """Records every POST; replies with the queued responses (default 200)."""

    def __init__(self, responses: list[Any] | None = None):
        self.posts: list[tuple[str, Any]] = []
        self.responses = list(responses or [])

    def post(self, url: str, *, json: Any, timeout: float):
        self.posts.append((url, json))
        if self.responses:
            answer = self.responses.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return FakeResponse()


@pytest.fixture
def rules() -> Rules:
    return Rules(min_drop_percent=10, median_window_days=30, back_in_stock=True)


@pytest.fixture
def item() -> WatchItem:
    return WatchItem(asin="B09XS7JWHH", name="Sony WH-1000XM5", target_price=179)


def observation(price: float | None, *, currency: str | None = "USD", **extra) -> Observation:
    fields = {
        "key": "amazon.com:B09XS7JWHH",
        "asin": "B09XS7JWHH",
        "marketplace": "amazon.com",
        "title": "Sony WH-1000XM5",
        "url": "https://www.amazon.com/dp/B09XS7JWHH",
        "price": price,
        "currency": currency if price is not None else None,
        "rating": 4.2,
        "review_count": 20334,
        "offers_count": 50,
        "offers_from_price": 177.99,
    }
    fields.update(extra)
    return Observation(**fields)


def make_alert(**overrides) -> Alert:
    fields = {
        "key": "amazon.com:B09XS7JWHH",
        "title": "Sony WH-1000XM5 headphones",
        "url": "https://www.amazon.com/dp/B09XS7JWHH",
        "marketplace": "amazon.com",
        "price": 169.0,
        "currency": "USD",
        "reasons": ("target", "drop", "lowest"),
        "target_price": 179.0,
        "median_price": 199.95,
        "median_window_days": 30,
        "drop_percent": 15.5,
        "previous_price": 199.95,
        "lowest_before": 199.95,
        "tracking_since": "2026-11-01",
        "list_price": 399.99,
        "rating": 4.2,
        "review_count": 20334,
        "offers_count": 50,
        "offers_from_price": 177.99,
    }
    fields.update(overrides)
    return Alert(**fields)
