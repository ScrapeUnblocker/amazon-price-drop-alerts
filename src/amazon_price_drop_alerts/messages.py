"""Turn alerts into the text each destination shows.

Every destination gets the same message; only the markup differs (Slack mrkdwn, Discord
markdown, Telegram HTML, plain text for the webhook and ``--dry-run``).
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .process import Alert

_PREFIX_SYMBOLS = {
    "USD": "$",
    "GBP": "£",
    "EUR": "€",
    "JPY": "¥",
    "INR": "₹",
    "CAD": "CA$",
    "AUD": "A$",
    "MXN": "MX$",
    "BRL": "R$",
    "SGD": "S$",
}
_NO_DECIMALS = {"JPY"}
TITLE_MAX = 110


def format_money(amount: float, currency: str | None) -> str:
    """``$199.95``, ``€89.00``, ``¥4,980`` or ``1,299.00 SEK``."""
    code = (currency or "").upper()
    number = f"{amount:,.0f}" if code in _NO_DECIMALS else f"{amount:,.2f}"
    if code in _PREFIX_SYMBOLS:
        return f"{_PREFIX_SYMBOLS[code]}{number}"
    return f"{number} {code}".strip()


@dataclass(frozen=True)
class Style:
    """How one destination writes bold text and links, and what it must escape."""

    name: str
    bold: Callable[[str], str]
    link: Callable[[str, str], str]
    escape: Callable[[str], str]


def _slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _discord_escape(text: str) -> str:
    text = re.sub(r"([\\*_~`\[\]])", r"\\\1", text)
    return text.replace("||", "\\|\\|")  # || starts a spoiler; a single | is plain text


def _telegram_escape(text: str) -> str:
    return html.escape(text, quote=False)


SLACK = Style(
    name="slack",
    bold=lambda text: f"*{text}*",
    link=lambda text, url: f"<{url}|{text}>",
    escape=_slack_escape,
)
DISCORD = Style(
    name="discord",
    bold=lambda text: f"**{text}**",
    link=lambda text, url: f"[{text}]({url})",
    escape=_discord_escape,
)
TELEGRAM = Style(
    name="telegram",
    bold=lambda text: f"<b>{text}</b>",
    link=lambda text, url: f'<a href="{html.escape(url, quote=True)}">{text}</a>',
    escape=_telegram_escape,
)
PLAIN = Style(
    name="plain",
    bold=lambda text: text,
    link=lambda text, url: f"{text}\n{url}",
    escape=lambda text: text,
)


def header(count: int, style: Style) -> str:
    noun = "item" if count == 1 else "items"
    return style.bold(f"Amazon price alert: {count} {noun} on your watchlist")


def reason_phrases(alert: Alert) -> list[str]:
    cur = alert.currency
    phrases: list[str] = []
    for reason in alert.reasons:
        if reason == "back_in_stock":
            phrases.append("back in stock")
        elif reason == "target" and alert.target_price is not None:
            phrases.append(f"at or below your target of {format_money(alert.target_price, cur)}")
        elif reason == "drop" and alert.drop_percent is not None and alert.median_price:
            phrases.append(
                f"{alert.drop_percent:.0f}% below its {alert.median_window_days}-day median "
                f"of {format_money(alert.median_price, cur)}"
            )
        elif reason == "lowest":
            since = f" on {alert.tracking_since}" if alert.tracking_since else ""
            phrases.append(f"lowest price since tracking began{since}")
    return phrases


def context_line(alert: Alert) -> str:
    cur = alert.currency
    parts: list[str] = []
    if alert.previous_price is not None and abs(alert.previous_price - alert.price) >= 0.005:
        parts.append(f"was {format_money(alert.previous_price, cur)} last check")
    if alert.list_price and alert.list_price > alert.price:
        parts.append(f"list price {format_money(alert.list_price, cur)}")
    if alert.rating is not None:
        rating = f"{alert.rating:g} stars"
        if alert.review_count:
            rating += f" ({alert.review_count:,} ratings)"
        parts.append(rating)
    if alert.offers_count and alert.offers_from_price is not None:
        offers_from = format_money(alert.offers_from_price, cur)
        parts.append(f"{alert.offers_count} offers from {offers_from}")
    parts.append(alert.marketplace)
    return " | ".join(parts)


def render_alert(alert: Alert, style: Style) -> str:
    title = alert.title if len(alert.title) <= TITLE_MAX else alert.title[: TITLE_MAX - 3] + "..."
    lines = [
        style.bold(style.link(style.escape(title), alert.url)),
        style.escape(
            " - ".join([format_money(alert.price, alert.currency), *reason_phrases(alert)])
        ),
        style.escape(context_line(alert)),
    ]
    return "\n".join(lines)


def render(alerts: Sequence[Alert], style: Style, limit: int | None = None) -> list[str]:
    """Render alerts as one or more messages, each at most ``limit`` characters.

    Messages split between items, never inside one; the header goes on the first.
    """
    blocks = [render_alert(alert, style) for alert in alerts]
    messages: list[str] = []
    current = header(len(alerts), style)
    for block in blocks:
        candidate = f"{current}\n\n{block}"
        if limit is not None and len(candidate) > limit and current:
            messages.append(current)
            candidate = block
        current = candidate
    messages.append(current)
    if limit is not None:
        messages = [m if len(m) <= limit else m[: limit - 3] + "..." for m in messages]
    return messages
