"""Decide which price changes are worth a message.

An item alerts when its price is at or below the user's ``target_price``, or at least
``min_drop_percent`` below the median of its recent daily prices. It alerts once per
price level: the same or a higher price never alerts twice, a lower one does, and the
item re-arms once the price climbs back out of alert range. An item that showed no price
on two checks in a row and has one again is reported as back in stock.
"""

from __future__ import annotations

import copy
import statistics
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from .collect import Observation
from .config import Rules, WatchItem

# A product must show no price this many checks in a row before "back in stock" counts,
# so one odd response does not cause a false restock message.
RESTOCK_CONFIRM_CHECKS = 2
# Daily prices kept per item in the state file.
HISTORY_DAYS = 365
# Prices closer than this are treated as equal.
EPSILON = 0.005

REASONS = ("back_in_stock", "target", "drop", "lowest")


@dataclass(frozen=True)
class Alert:
    """One product worth telling the user about, with everything the message shows."""

    key: str
    title: str
    url: str
    marketplace: str
    price: float
    currency: str | None
    reasons: tuple[str, ...]
    target_price: float | None = None
    median_price: float | None = None
    median_window_days: int = 30
    drop_percent: float | None = None
    previous_price: float | None = None
    lowest_before: float | None = None
    tracking_since: str | None = None
    list_price: float | None = None
    rating: float | None = None
    review_count: int | None = None
    offers_count: int | None = None
    offers_from_price: float | None = None
    image: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def new_item_state(obs: Observation, today: date) -> dict[str, Any]:
    return {
        "title": obs.title,
        "url": obs.url,
        "currency": obs.currency,
        "first_seen": today.isoformat(),
        "last_price": None,
        "lowest_price": None,
        "lowest_date": None,
        "last_alert_price": None,
        "unavailable_checks": 0,
        "history": {},
    }


def evaluate(
    item: WatchItem,
    obs: Observation,
    prev: dict[str, Any] | None,
    rules: Rules,
    today: date,
) -> tuple[Alert | None, dict[str, Any]]:
    """Compare this run's observation with the stored state.

    Returns the alert to deliver (or ``None``) and the item's new state. ``prev`` is
    never modified, so a caller can keep it if delivery fails.
    """
    state = copy.deepcopy(prev) if prev else new_item_state(obs, today)
    state["title"] = obs.title
    state["url"] = obs.url

    if not obs.available:
        state["unavailable_checks"] = int(state.get("unavailable_checks") or 0) + 1
        return None, state

    if prev and prev.get("currency") and obs.currency and prev["currency"] != obs.currency:
        # Prices in another currency are not comparable with the history: start over.
        state = new_item_state(obs, today)
    price = float(obs.price)  # type: ignore[arg-type]
    history: dict[str, float] = state.setdefault("history", {})

    median = median_price(state, rules.median_window_days, today)
    drop_percent = (median - price) / median * 100 if median and price < median else None

    hit_target = item.target_price is not None and price <= item.target_price + EPSILON
    hit_drop = drop_percent is not None and drop_percent >= item.drop_threshold(rules)
    lowest_before = state.get("lowest_price")
    previous_price = state.get("last_price")
    was_unavailable = int(state.get("unavailable_checks") or 0) >= RESTOCK_CONFIRM_CHECKS

    reasons: list[str] = []
    if was_unavailable and item.wants_back_in_stock(rules):
        reasons.append("back_in_stock")
    last_alert = state.get("last_alert_price")
    if hit_target or hit_drop:
        if last_alert is None or price < last_alert - EPSILON:
            if hit_target:
                reasons.append("target")
            if hit_drop:
                reasons.append("drop")
            if lowest_before is not None and price < lowest_before - EPSILON:
                reasons.append("lowest")
            state["last_alert_price"] = price
    else:
        state["last_alert_price"] = None

    history[today.isoformat()] = price
    for day in sorted(history)[:-HISTORY_DAYS]:
        del history[day]
    state["history"] = dict(sorted(history.items()))
    state["last_price"] = price
    state["currency"] = obs.currency
    state["unavailable_checks"] = 0
    if lowest_before is None or price < lowest_before - EPSILON:
        state["lowest_price"] = price
        state["lowest_date"] = today.isoformat()

    if not reasons:
        return None, state
    alert = Alert(
        key=obs.key,
        title=obs.title,
        url=obs.url,
        marketplace=obs.marketplace,
        price=price,
        currency=obs.currency,
        reasons=tuple(r for r in REASONS if r in reasons),
        target_price=item.target_price,
        median_price=median,
        median_window_days=rules.median_window_days,
        drop_percent=round(drop_percent, 1) if drop_percent is not None else None,
        previous_price=previous_price,
        lowest_before=lowest_before,
        tracking_since=state.get("first_seen"),
        list_price=obs.list_price,
        rating=obs.rating,
        review_count=obs.review_count,
        offers_count=obs.offers_count,
        offers_from_price=obs.offers_from_price,
        image=obs.image,
    )
    return alert, state


def median_price(state: dict[str, Any], window_days: int, today: date) -> float | None:
    """Median of the stored daily prices from the last ``window_days`` days.

    Today's entry, if an earlier run today recorded one, is part of the window.
    """
    cutoff = (today - timedelta(days=window_days)).isoformat()
    window = [p for day, p in (state.get("history") or {}).items() if day > cutoff]
    return statistics.median(window) if window else None
