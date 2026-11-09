import json

import pytest

from amazon_price_drop_alerts.state import StateError, load_state, save_state


def test_missing_file_is_empty_state(tmp_path):
    assert load_state(tmp_path / "prices.json") == {}


def test_round_trip_and_unchanged_detection(tmp_path):
    path = tmp_path / "state" / "prices.json"
    items = {"amazon.com:B": {"history": {"2026-11-01": 2.0}}, "amazon.com:A": {"history": {}}}
    assert save_state(path, items) is True
    assert load_state(path) == items
    assert save_state(path, items) is False  # same content: no rewrite, no commit
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert list(data["items"]) == ["amazon.com:A", "amazon.com:B"]
    assert not list(path.parent.glob("*.tmp"))


def test_corrupt_file_raises(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StateError):
        load_state(path)
