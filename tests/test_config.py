from pathlib import Path

import pytest

from amazon_price_drop_alerts.config import (
    DESTINATIONS,
    ConfigError,
    load_config,
    parse_amazon_url,
    parse_config,
)

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config.yml"


def test_shipped_config_is_valid():
    config = load_config(REPO_CONFIG)
    assert len(config.watchlist) == 3
    assert config.destinations == DESTINATIONS
    assert config.state_file == REPO_CONFIG.parent / "state" / "prices.json"
    assert config.watchlist[0].key == "amazon.com:B09XS7JWHH"
    assert config.watchlist[0].target_price == 179.0


def test_defaults_and_overrides():
    config = parse_config(
        {
            "watchlist": [
                {"asin": "b09xs7jwhh"},
                {"asin": "B0CFPJYX7P", "marketplace": "amazon.de", "min_drop_percent": 25},
            ],
            "rules": {"min_drop_percent": 12.5, "back_in_stock": False},
        }
    )
    first, second = config.watchlist
    assert first.asin == "B09XS7JWHH" and first.marketplace == "amazon.com"
    assert first.drop_threshold(config.rules) == 12.5
    assert second.drop_threshold(config.rules) == 25
    assert second.key == "amazon.de:B0CFPJYX7P"
    assert first.wants_back_in_stock(config.rules) is False
    assert config.rules.median_window_days == 30
    assert config.state_file == Path("state/prices.json")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.amazon.com/dp/B09XS7JWHH", ("B09XS7JWHH", "amazon.com")),
        (
            "https://www.amazon.co.uk/Sony-WH-1000XM5/dp/b09xs7jwhh/ref=sr_1_1?k=x",
            ("B09XS7JWHH", "amazon.co.uk"),
        ),
        ("https://amazon.de/gp/product/B0CFPJYX7P", ("B0CFPJYX7P", "amazon.de")),
        ("https://www.amazon.com.au/dp/B0CFPJYX7P?th=1", ("B0CFPJYX7P", "amazon.com.au")),
    ],
)
def test_parse_amazon_url(url, expected):
    assert parse_amazon_url(url) == expected


def test_url_item_in_config():
    config = parse_config({"watchlist": ["https://www.amazon.fr/dp/B09XS7JWHH"]})
    assert config.watchlist[0].key == "amazon.fr:B09XS7JWHH"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({}, "watchlist"),
        ({"watchlist": [{"name": "x"}]}, "give an 'asin'"),
        ({"watchlist": [{"asin": "SHORT"}]}, "10-character ASIN"),
        ({"watchlist": [{"asin": "B09XS7JWHH", "marketplace": "amazon.xyz"}]}, "marketplace"),
        ({"watchlist": [{"url": "https://example.com/dp/B09XS7JWHH"}]}, "supported Amazon"),
        ({"watchlist": [{"url": "https://www.amazon.com/s?k=headphones"}]}, "could not find"),
        ({"watchlist": [{"asin": "B09XS7JWHH", "target": 100}]}, "unknown key"),
        ({"watchlist": [{"asin": "B09XS7JWHH", "target_price": -5}]}, "positive"),
        ({"watchlist": ["B09XS7JWHH", "B09XS7JWHH"]}, "listed twice"),
        ({"watchlist": ["B09XS7JWHH"], "destinations": ["email"]}, "unknown destination"),
        ({"watchlist": ["B09XS7JWHH"], "rules": {"min_drop_percent": 0}}, "between 0 and 100"),
        ({"watchlist": ["B09XS7JWHH"], "rules": {"median_window_days": 0}}, "1 to 365"),
        ({"watchlist": ["B09XS7JWHH"], "rules": {"back_in_stock": "yes"}}, "true or false"),
        ({"watchlist": ["B09XS7JWHH"], "colour": "red"}, "unknown key"),
    ],
)
def test_invalid_config(raw, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(raw)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yml")
