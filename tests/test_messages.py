import pytest
from conftest import make_alert

from amazon_price_drop_alerts import messages


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (199.95, "USD", "$199.95"),
        (1299.0, "EUR", "€1,299.00"),
        (4980.0, "JPY", "¥4,980"),
        (1299.5, "SEK", "1,299.50 SEK"),
        (12.0, None, "12.00"),
    ],
)
def test_format_money(amount, currency, expected):
    assert messages.format_money(amount, currency) == expected


def test_plain_message():
    text = messages.render([make_alert()], messages.PLAIN)[0]
    assert text == (
        "Amazon price alert: 1 item on your watchlist\n"
        "\n"
        "Sony WH-1000XM5 headphones\n"
        "https://www.amazon.com/dp/B09XS7JWHH\n"
        "$169.00 - at or below your target of $179.00 - 16% below its 30-day median of $199.95"
        " - lowest price since tracking began on 2026-11-01\n"
        "was $199.95 last check | list price $399.99 | 4.2 stars (20,334 ratings)"
        " | 50 offers from $177.99 | amazon.com"
    )


def test_slack_markup_and_escaping():
    alert = make_alert(title="Cables & <Adapters>", reasons=("back_in_stock",))
    lines = messages.render([alert], messages.SLACK)[0].split("\n")
    assert lines[0] == "*Amazon price alert: 1 item on your watchlist*"
    assert lines[2] == "*<https://www.amazon.com/dp/B09XS7JWHH|Cables &amp; &lt;Adapters&gt;>*"
    assert lines[3] == "$169.00 - back in stock"


def test_discord_markup():
    text = messages.render([make_alert(title="Best_Seller *Deal*")], messages.DISCORD)[0]
    assert "**[Best\\_Seller \\*Deal\\*](https://www.amazon.com/dp/B09XS7JWHH)**" in text
    assert text.startswith("**Amazon price alert: 1 item on your watchlist**")
    # A single | is plain text in Discord and stays readable; || (spoiler) is escaped.
    assert "4.2 stars (20,334 ratings) | 50 offers from $177.99 | amazon.com" in text
    spoiler = messages.render([make_alert(title="A || B")], messages.DISCORD)[0]
    assert "[A \\|\\| B]" in spoiler


def test_telegram_html():
    text = messages.render([make_alert(title="Tom & Jerry <DVD>")], messages.TELEGRAM)[0]
    assert (
        '<b><a href="https://www.amazon.com/dp/B09XS7JWHH">Tom &amp; Jerry &lt;DVD&gt;</a></b>'
        in text
    )


def test_header_counts_items():
    text = messages.render([make_alert(), make_alert(key="b")], messages.PLAIN)[0]
    assert text.startswith("Amazon price alert: 2 items on your watchlist")


def test_long_title_is_truncated():
    text = messages.render([make_alert(title="x" * 300)], messages.PLAIN)[0]
    assert ("x" * (messages.TITLE_MAX - 3)) + "...\n" in text


def test_optional_fields_are_left_out():
    alert = make_alert(
        previous_price=None,
        list_price=None,
        rating=None,
        offers_count=None,
        reasons=("target",),
    )
    context = messages.render([alert], messages.PLAIN)[0].splitlines()[-1]
    assert context == "amazon.com"


def test_splits_between_items_when_over_limit():
    alerts = [make_alert(key=str(i)) for i in range(10)]
    chunks = messages.render(alerts, messages.DISCORD, limit=1000)
    assert len(chunks) > 1
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert chunks[0].startswith("**Amazon price alert: 10 items")
    assert sum(chunk.count("](https://www.amazon.com/dp/") for chunk in chunks) == 10
