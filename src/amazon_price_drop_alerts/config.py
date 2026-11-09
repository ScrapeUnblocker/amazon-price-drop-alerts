"""Load and validate ``config.yml``, the one file a user edits."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

# Regional Amazon sites the ScrapeUnblocker Amazon product API supports.
MARKETPLACES = (
    "amazon.com",
    "amazon.co.uk",
    "amazon.de",
    "amazon.fr",
    "amazon.it",
    "amazon.es",
    "amazon.nl",
    "amazon.se",
    "amazon.pl",
    "amazon.com.be",
    "amazon.com.tr",
    "amazon.ca",
    "amazon.com.mx",
    "amazon.com.br",
    "amazon.co.jp",
    "amazon.in",
    "amazon.ae",
    "amazon.sa",
    "amazon.sg",
    "amazon.com.au",
)

DESTINATIONS = ("slack", "discord", "telegram", "webhook")

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
_URL_ASIN_RE = re.compile(
    r"/(?:dp|gp/product|gp/aw/d|exec/obidos/ASIN)/([A-Za-z0-9]{10})(?:[/?#]|$)"
)
_ITEM_KEYS = {
    "asin",
    "url",
    "marketplace",
    "name",
    "target_price",
    "min_drop_percent",
    "back_in_stock",
}
_RULE_KEYS = {"min_drop_percent", "median_window_days", "back_in_stock"}
_TOP_KEYS = {"watchlist", "rules", "destinations", "state_file"}


class ConfigError(ValueError):
    """The config file is missing, unreadable or has an invalid value."""


@dataclass(frozen=True)
class Rules:
    """Alert rules that apply to every watchlist item unless the item overrides them."""

    min_drop_percent: float = 10.0
    median_window_days: int = 30
    back_in_stock: bool = True


@dataclass(frozen=True)
class WatchItem:
    """One Amazon product on the watchlist."""

    asin: str
    marketplace: str = "amazon.com"
    name: str | None = None
    target_price: float | None = None
    min_drop_percent: float | None = None
    back_in_stock: bool | None = None

    @property
    def key(self) -> str:
        """Stable id used in the state file, e.g. ``amazon.com:B09XS7JWHH``."""
        return f"{self.marketplace}:{self.asin}"

    @property
    def product_url(self) -> str:
        return f"https://www.{self.marketplace}/dp/{self.asin}"

    def drop_threshold(self, rules: Rules) -> float:
        if self.min_drop_percent is not None:
            return self.min_drop_percent
        return rules.min_drop_percent

    def wants_back_in_stock(self, rules: Rules) -> bool:
        if self.back_in_stock is not None:
            return self.back_in_stock
        return rules.back_in_stock


@dataclass(frozen=True)
class Config:
    watchlist: tuple[WatchItem, ...]
    rules: Rules
    destinations: tuple[str, ...]
    state_file: Path


def parse_amazon_url(url: str) -> tuple[str, str]:
    """Return ``(asin, marketplace)`` for an Amazon product URL."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    for prefix in ("www.", "smile.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
            break
    if host not in MARKETPLACES:
        raise ConfigError(f"{url!r} is not a product URL on a supported Amazon marketplace")
    match = _URL_ASIN_RE.search(parsed.path)
    if not match:
        raise ConfigError(f"could not find an ASIN (/dp/XXXXXXXXXX) in {url!r}")
    return match.group(1).upper(), host


def load_config(path: str | Path) -> Config:
    """Read and validate a config file. Relative ``state_file`` paths resolve next to it."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from None
    config = parse_config(raw or {})
    state_file = config.state_file
    if not state_file.is_absolute():
        state_file = path.parent / state_file
    return Config(config.watchlist, config.rules, config.destinations, state_file)


def parse_config(raw: Any) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("the config must be a mapping with a 'watchlist' list")
    _reject_unknown(raw, _TOP_KEYS, "config")

    rules = _parse_rules(raw.get("rules") or {})

    items_raw = raw.get("watchlist")
    if not isinstance(items_raw, list) or not items_raw:
        raise ConfigError("'watchlist' must be a non-empty list of products")
    items: list[WatchItem] = []
    seen: set[str] = set()
    for index, entry in enumerate(items_raw, start=1):
        item = _parse_item(entry, index)
        if item.key in seen:
            raise ConfigError(f"watchlist item {index}: {item.key} is listed twice")
        seen.add(item.key)
        items.append(item)

    destinations = raw.get("destinations", list(DESTINATIONS))
    if isinstance(destinations, str):
        destinations = [destinations]
    if not isinstance(destinations, list) or not destinations:
        raise ConfigError(f"'destinations' must be a list, any of: {', '.join(DESTINATIONS)}")
    for name in destinations:
        if name not in DESTINATIONS:
            raise ConfigError(
                f"unknown destination {name!r}; use any of: {', '.join(DESTINATIONS)}"
            )

    state_file = raw.get("state_file", "state/prices.json")
    if not isinstance(state_file, str) or not state_file.strip():
        raise ConfigError("'state_file' must be a file path")

    return Config(
        watchlist=tuple(items),
        rules=rules,
        destinations=tuple(dict.fromkeys(destinations)),
        state_file=Path(state_file),
    )


def _parse_rules(raw: Any) -> Rules:
    if not isinstance(raw, dict):
        raise ConfigError("'rules' must be a mapping")
    _reject_unknown(raw, _RULE_KEYS, "rules")
    defaults = Rules()
    drop = _percent(
        raw.get("min_drop_percent", defaults.min_drop_percent), "rules.min_drop_percent"
    )
    window = raw.get("median_window_days", defaults.median_window_days)
    if isinstance(window, bool) or not isinstance(window, int) or not 1 <= window <= 365:
        raise ConfigError("rules.median_window_days must be a whole number from 1 to 365")
    restock = raw.get("back_in_stock", defaults.back_in_stock)
    if not isinstance(restock, bool):
        raise ConfigError("rules.back_in_stock must be true or false")
    return Rules(min_drop_percent=drop, median_window_days=window, back_in_stock=restock)


def _parse_item(raw: Any, index: int) -> WatchItem:
    where = f"watchlist item {index}"
    if isinstance(raw, str):
        raw = {"url": raw} if raw.startswith("http") else {"asin": raw}
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: expected a mapping with 'asin' or 'url'")
    _reject_unknown(raw, _ITEM_KEYS, where)

    if raw.get("url"):
        asin, marketplace = parse_amazon_url(str(raw["url"]))
        if raw.get("asin") and str(raw["asin"]).strip().upper() != asin:
            raise ConfigError(f"{where}: 'asin' and 'url' point at different products")
    elif raw.get("asin"):
        asin = str(raw["asin"]).strip().upper()
        marketplace = str(raw.get("marketplace") or "amazon.com").strip().lower()
        if not _ASIN_RE.match(asin):
            raise ConfigError(f"{where}: {raw['asin']!r} is not a 10-character ASIN")
    else:
        raise ConfigError(f"{where}: give an 'asin' or a product 'url'")
    if marketplace not in MARKETPLACES:
        raise ConfigError(f"{where}: unsupported marketplace {marketplace!r}")

    target = raw.get("target_price")
    if target is not None:
        if isinstance(target, bool) or not isinstance(target, int | float) or target <= 0:
            raise ConfigError(f"{where}: target_price must be a positive number")
        target = float(target)

    drop = raw.get("min_drop_percent")
    if drop is not None:
        drop = _percent(drop, f"{where}: min_drop_percent")

    restock = raw.get("back_in_stock")
    if restock is not None and not isinstance(restock, bool):
        raise ConfigError(f"{where}: back_in_stock must be true or false")

    name = raw.get("name")
    return WatchItem(
        asin=asin,
        marketplace=marketplace,
        name=str(name).strip() if name else None,
        target_price=target,
        min_drop_percent=drop,
        back_in_stock=restock,
    )


def _percent(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value < 100:
        raise ConfigError(f"{where} must be a number between 0 and 100")
    return float(value)


def _reject_unknown(raw: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {', '.join(map(repr, unknown))}; "
            f"allowed: {', '.join(sorted(allowed))}"
        )
