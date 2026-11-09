import pytest
from conftest import FakeClient, product_payload
from scrapeunblocker.exceptions import (
    AuthenticationError,
    NotFoundError,
    ScrapeTimeoutError,
    ServerError,
)

from amazon_price_drop_alerts.collect import collect, fetch, shape
from amazon_price_drop_alerts.config import WatchItem

ITEM = WatchItem(asin="B09XS7JWHH")
NO_SLEEP = {"sleep": lambda _seconds: None}


def test_shape_reads_the_fields_alerts_use():
    obs = shape(ITEM, product_payload(listPrice=249.99, inStock=True))
    assert obs.key == "amazon.com:B09XS7JWHH"
    assert obs.title.startswith("Sony WH-1000XM5")
    assert obs.price == 199.95 and obs.currency == "USD"
    assert obs.list_price == 249.99
    assert obs.in_stock is True and obs.available
    assert obs.review_count == 20334
    assert obs.offers_count == 50 and obs.offers_from_price == 177.99


def test_shape_without_price_is_unavailable():
    obs = shape(ITEM, product_payload(price=None))
    assert obs.price is None
    assert not obs.available


def test_name_overrides_title_and_url_falls_back():
    item = WatchItem(asin="B09XS7JWHH", name="My headphones")
    obs = shape(item, product_payload(url=None))
    assert obs.title == "My headphones"
    assert obs.url == "https://www.amazon.com/dp/B09XS7JWHH"


def test_retries_a_blocked_call_then_succeeds():
    client = FakeClient(
        {"B09XS7JWHH": [ServerError("bot wall", status_code=502), product_payload()]}
    )
    obs = fetch(client, ITEM, **NO_SLEEP)
    assert obs.price == 199.95
    assert client.calls == [("B09XS7JWHH", "amazon.com"), ("B09XS7JWHH", "amazon.com")]


def test_failed_item_is_reported_not_raised():
    client = FakeClient(
        {
            "B09XS7JWHH": [ScrapeTimeoutError("slow"), ScrapeTimeoutError("slow")],
            "B0CFPJYX7P": NotFoundError("no such product", status_code=404),
            "B09B8V1LZ3": product_payload("B09B8V1LZ3", 79.99),
        }
    )
    items = [ITEM, WatchItem(asin="B0CFPJYX7P"), WatchItem(asin="B09B8V1LZ3")]
    result = collect(client, items, **NO_SLEEP)
    assert [o.asin for o in result.observations] == ["B09B8V1LZ3"]
    assert [(i.asin, e.split(":")[0]) for i, e in result.failures] == [
        ("B09XS7JWHH", "ScrapeTimeoutError"),
        ("B0CFPJYX7P", "NotFoundError"),
    ]
    # The 404 is not retried; the timeout is tried twice.
    assert client.calls.count(("B0CFPJYX7P", "amazon.com")) == 1
    assert client.calls.count(("B09XS7JWHH", "amazon.com")) == 2


def test_bad_key_stops_the_run():
    client = FakeClient({"B09XS7JWHH": AuthenticationError("bad key", status_code=401)})
    with pytest.raises(AuthenticationError):
        collect(client, [ITEM], **NO_SLEEP)
