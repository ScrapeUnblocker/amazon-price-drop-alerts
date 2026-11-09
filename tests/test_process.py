from datetime import date, timedelta

from conftest import observation

from amazon_price_drop_alerts.config import Rules, WatchItem
from amazon_price_drop_alerts.process import HISTORY_DAYS, evaluate

DAY1 = date(2026, 11, 1)


def run_days(item, rules, prices, start=DAY1, state=None):
    """Evaluate one price per day; return the alerts per day and the final state."""
    alerts = []
    for offset, price in enumerate(prices):
        alert, state = evaluate(item, observation(price), state, rules, start + timedelta(offset))
        alerts.append(alert)
    return alerts, state


def test_first_run_above_target_records_baseline(item, rules):
    alert, state = evaluate(item, observation(199.95), None, rules, DAY1)
    assert alert is None
    assert state["history"] == {"2026-11-01": 199.95}
    assert state["last_price"] == 199.95
    assert state["lowest_price"] == 199.95
    assert state["first_seen"] == "2026-11-01"
    assert state["last_alert_price"] is None


def test_first_run_already_below_target_alerts(item, rules):
    alert, state = evaluate(item, observation(169.0), None, rules, DAY1)
    assert alert is not None
    assert alert.reasons == ("target",)
    assert alert.target_price == 179
    assert state["last_alert_price"] == 169.0


def test_same_price_never_alerts_twice(item, rules):
    alerts, state = run_days(item, rules, [169.0, 169.0, 169.0])
    assert [a is not None for a in alerts] == [True, False, False]


def test_lower_price_alerts_again(item, rules):
    alerts, _ = run_days(item, rules, [169.0, 169.0, 159.0])
    assert alerts[2] is not None
    assert alerts[2].price == 159.0
    assert alerts[2].previous_price == 169.0
    assert "lowest" in alerts[2].reasons


def test_rearms_after_price_recovers(item, rules):
    alerts, state = run_days(item, rules, [169.0, 199.0, 169.0])
    assert alerts[0] is not None
    assert alerts[1] is None
    assert alerts[2] is not None and alerts[2].reasons[0] == "target"


def test_drop_against_median(rules):
    item = WatchItem(asin="B09XS7JWHH")  # no target: only the median rule
    alerts, _ = run_days(item, rules, [200.0, 200.0, 200.0, 198.0, 175.0])
    assert alerts[:4] == [None, None, None, None]
    drop = alerts[4]
    assert drop is not None
    assert drop.reasons == ("drop", "lowest")
    assert drop.median_price == 200.0
    assert drop.drop_percent == 12.5
    assert drop.tracking_since == "2026-11-01"


def test_small_drop_below_threshold_is_quiet(rules):
    item = WatchItem(asin="B09XS7JWHH")
    alerts, state = run_days(item, rules, [200.0, 200.0, 185.0])
    assert alerts == [None, None, None]
    assert state["lowest_price"] == 185.0


def test_per_item_threshold_override(rules):
    item = WatchItem(asin="B09XS7JWHH", min_drop_percent=30)
    alerts, _ = run_days(item, rules, [200.0, 200.0, 150.0])
    assert alerts[2] is None


def test_median_window_ignores_old_prices():
    rules = Rules(min_drop_percent=10, median_window_days=3)
    item = WatchItem(asin="B09XS7JWHH")
    # By the last run the 400s are 3+ days old: outside a 3-day window the median is 200,
    # so 190 is only 5% below it. A 30-day median (400) would have alerted.
    alerts, _ = run_days(item, rules, [400.0, 400.0, 400.0, 200.0, 200.0, 190.0])
    assert alerts[-1] is None
    long_alerts, _ = run_days(item, Rules(), [400.0, 400.0, 400.0, 200.0, 200.0, 190.0])
    assert long_alerts[-1] is not None


def test_same_day_runs_compare_with_earlier_check(rules):
    item = WatchItem(asin="B09XS7JWHH")
    _, state = evaluate(item, observation(200.0), None, rules, DAY1)
    alert, state = evaluate(item, observation(170.0), state, rules, DAY1)
    assert alert is not None and alert.reasons[0] == "drop"
    assert state["history"] == {"2026-11-01": 170.0}


def test_back_in_stock_needs_two_empty_checks(item, rules):
    _, state = evaluate(item, observation(199.95), None, rules, DAY1)
    _, state = evaluate(item, observation(None), state, rules, DAY1 + timedelta(1))
    alert, state = evaluate(item, observation(199.95), state, rules, DAY1 + timedelta(2))
    assert alert is None  # one empty check could be noise

    _, state = evaluate(item, observation(None), state, rules, DAY1 + timedelta(3))
    _, state = evaluate(item, observation(None), state, rules, DAY1 + timedelta(4))
    assert state["unavailable_checks"] == 2
    alert, state = evaluate(item, observation(199.95), state, rules, DAY1 + timedelta(5))
    assert alert is not None and alert.reasons == ("back_in_stock",)
    assert state["unavailable_checks"] == 0


def test_back_in_stock_can_be_turned_off(rules):
    item = WatchItem(asin="B09XS7JWHH", back_in_stock=False)
    state = None
    for offset, price in enumerate([None, None, 199.95]):
        alert, state = evaluate(item, observation(price), state, rules, DAY1 + timedelta(offset))
    assert alert is None


def test_unavailable_check_keeps_history(item, rules):
    _, state = evaluate(item, observation(199.95), None, rules, DAY1)
    alert, after = evaluate(item, observation(None), state, rules, DAY1 + timedelta(1))
    assert alert is None
    assert after["history"] == state["history"]
    assert after["last_price"] == 199.95


def test_in_stock_false_counts_as_unavailable(item, rules):
    obs = observation(199.95, in_stock=False)
    _, state = evaluate(item, obs, None, rules, DAY1)
    assert state["unavailable_checks"] == 1
    assert state["history"] == {}


def test_currency_change_restarts_history(item, rules):
    _, state = evaluate(item, observation(199.95), None, rules, DAY1)
    alert, state = evaluate(item, observation(150.0, currency="EUR"), state, rules, DAY1)
    assert state["currency"] == "EUR"
    assert state["history"] == {"2026-11-01": 150.0}
    assert alert is not None and "drop" not in alert.reasons


def test_history_is_trimmed(rules):
    item = WatchItem(asin="B09XS7JWHH")
    _, state = run_days(item, rules, [100.0] * (HISTORY_DAYS + 5))
    assert len(state["history"]) == HISTORY_DAYS
    assert min(state["history"]) == (DAY1 + timedelta(5)).isoformat()


def test_evaluate_does_not_mutate_previous_state(item, rules):
    _, state = evaluate(item, observation(199.95), None, rules, DAY1)
    before = {**state, "history": dict(state["history"])}
    evaluate(item, observation(150.0), state, rules, DAY1 + timedelta(1))
    assert state == before
