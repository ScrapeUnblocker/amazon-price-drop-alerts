"""Amazon price-drop alerts for a watchlist, delivered to Slack, Discord, Telegram or a webhook.

Prices come from the ScrapeUnblocker Amazon product API:
https://docs.scrapeunblocker.com/plugins/amazon?utm_source=github&utm_medium=integration&utm_campaign=example-repos
"""

from .collect import Observation, collect
from .config import Config, ConfigError, Rules, WatchItem, load_config
from .process import Alert, evaluate

__all__ = [
    "Alert",
    "Config",
    "ConfigError",
    "Observation",
    "Rules",
    "WatchItem",
    "collect",
    "evaluate",
    "load_config",
]

__version__ = "0.1.0"
