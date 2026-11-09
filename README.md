# Amazon price-drop alerts

For anyone waiting on a better Amazon price: when a product on your watchlist hits your target price or drops well below its recent median, a message lands in your Slack, Discord or Telegram (or any webhook) at the next check, every 6 hours by default.

[![CI](https://github.com/ScrapeUnblocker/amazon-price-drop-alerts/actions/workflows/ci.yml/badge.svg)](https://github.com/ScrapeUnblocker/amazon-price-drop-alerts/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Powered by ScrapeUnblocker](https://img.shields.io/badge/powered%20by-ScrapeUnblocker-6c47ff.svg)](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)

It runs on a GitHub Actions schedule in your own copy of this repo. Nothing to host, and you only hear about it when something changed.

## What actually arrives

This is the real message from a test run. The target was set to $250 so the test would trigger an alert:

```text
Amazon price alert: 1 item on your watchlist

Sony WH-1000XM5 headphones
https://www.amazon.com/dp/B09XS7JWHH
$189.99 - at or below your target of $250.00
4.2 stars (20,334 ratings) | 52 offers from $177.99 | amazon.com
```

Slack, Discord and Telegram get the same text with a bold, linked title. The generic webhook gets it as `text`, plus every alert as structured JSON in `alerts`. Besides the target, an alert can also say:

- `N% below its 30-day median of $X`: a real drop, not just a cheap day compared with yesterday
- `lowest price since tracking began on <date>`
- `back in stock`: the item showed no price on 2 checks in a row and now has one
- `was $X last check` and `list price $X`, when they apply

Several items that alert in the same run arrive as one message.

## Setup in three steps

1. **Use this template.** Click **Use this template** > **Create a new repository**. Make it private if you would rather not publish your watchlist.
2. **Add secrets.** In your new repo go to **Settings > Secrets and variables > Actions** and add:
   - `SCRAPEUNBLOCKER_KEY`: your API key from [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
   - at least one destination:

   | Destination | Secret(s) | Where to get it |
   | - | - | - |
   | Slack | `SLACK_WEBHOOK_URL` | [Create an incoming webhook](https://api.slack.com/messaging/webhooks) for a channel |
   | Discord | `DISCORD_WEBHOOK_URL` | Channel settings > Integrations > Webhooks > New Webhook > Copy Webhook URL |
   | Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Create a bot with [@BotFather](https://t.me/BotFather), send it a message, then read `chat.id` from `https://api.telegram.org/bot<token>/getUpdates` |
   | Webhook | `ALERT_WEBHOOK_URL` | Any URL that accepts a JSON POST: Zapier, Make, n8n or your own endpoint |

3. **Edit `config.yml`.** Put your products in `watchlist`, as an ASIN or a pasted product URL, and set a `target_price` where you have one in mind. Commit the change.

The workflow then checks every 6 hours. To start right away, open **Actions > Price check > Run workflow**. Tick **Dry run** to see the message without sending it. To check your destination secrets, run `amazon-price-drop-alerts test-destinations` locally, which posts a short "connected" message.

Until `SCRAPEUNBLOCKER_KEY` is set, the workflow prints a notice and exits green without doing anything.

### Run it on your own machine instead

```bash
git clone https://github.com/<you>/amazon-price-drop-alerts && cd amazon-price-drop-alerts
python -m venv .venv && . .venv/bin/activate
pip install .
cp .env.example .env              # fill in SCRAPEUNBLOCKER_KEY and a destination
amazon-price-drop-alerts run --dry-run
amazon-price-drop-alerts run
```

Then schedule it with cron (`crontab -e`). This line checks every 6 hours:

```cron
23 */6 * * * cd /path/to/amazon-price-drop-alerts && .venv/bin/amazon-price-drop-alerts run >> alerts.log 2>&1
```

The CLI reads `.env` from the working directory, and environment variables win over it. State is kept in `state/prices.json` next to `config.yml`.

## How it works

1. **Collect.** One call per watchlist item to the ScrapeUnblocker [Amazon product API](https://docs.scrapeunblocker.com/plugins/amazon?utm_source=github&utm_medium=integration&utm_campaign=example-repos) through the official Python SDK (`su.amazon_product(asin=..., marketplace=...)`). It returns the buy-box price and currency, list price, rating, review count and the number of other offers and their lowest price. Requests are routed from the marketplace's home country, so amazon.de comes back in EUR and amazon.co.uk in GBP. A blocked or timed-out call is retried once after a pause. A product that still fails is reported in the log and skipped; its state is left untouched.
2. **Process.** Each price is compared with the item's stored history:
   - **target:** the price is at or below your `target_price`.
   - **drop:** the price is at least `min_drop_percent` below the median of its daily prices over the last `median_window_days`. A median ignores one-day spikes, so a price that briefly jumped and came back does not count as a drop.
   - **once per price level:** after an alert, the same or a higher price never alerts again; only a lower one does. When the price climbs back out of alert range, the item re-arms.
   - **back in stock:** no price on 2 checks in a row, then a price again. A single odd response is not enough.
3. **Deliver.** Alerts are rendered for each destination (Slack mrkdwn, Discord markdown, Telegram HTML, plain text plus JSON for the webhook). Long messages are split between items. If no destination accepts the message, the alerted items keep their previous state, so the next run tries again.
4. **Save state.** `state/prices.json` holds one price per item per day for up to a year, the lowest price seen and the price you were last alerted at. The workflow commits it back to the repo after each run (`Update price history [skip ci]`). It only changes when a price moves or a new day starts, and doubles as a price history you can read. A second run with nothing new sends nothing and leaves the file as it was.

Two commands make no API calls: `amazon-price-drop-alerts status` prints what the state knows (last price, median, lowest, target, last alert) and `test-destinations` checks your secrets.

## Config reference

Everything lives in [`config.yml`](config.yml). Secrets never go there.

| Key | Default | Meaning |
| - | - | - |
| `watchlist[].asin` | (required, or `url`) | 10-character Amazon product id |
| `watchlist[].url` | | A product URL instead of `asin`, e.g. `https://www.amazon.co.uk/dp/B0...`; the ASIN and marketplace are read from it |
| `watchlist[].marketplace` | `amazon.com` | One of amazon.com, .co.uk, .de, .fr, .it, .es, .nl, .se, .pl, .com.be, .com.tr, .ca, .com.mx, .com.br, .co.jp, .in, .ae, .sa, .sg, .com.au |
| `watchlist[].name` | Amazon's title | Shorter label for the message |
| `watchlist[].target_price` | none | Alert when the price is at or below this (marketplace currency) |
| `watchlist[].min_drop_percent` | `rules.min_drop_percent` | Per-item override |
| `watchlist[].back_in_stock` | `rules.back_in_stock` | Per-item override |
| `rules.min_drop_percent` | `10` | Alert when the price is this many percent below its recent median |
| `rules.median_window_days` | `30` | How many days of daily prices the median uses (1-365) |
| `rules.back_in_stock` | `true` | Alert when an item that had no price on 2 checks in a row has one again |
| `destinations` | all four | Any of `slack`, `discord`, `telegram`, `webhook`. A listed destination without its secret is skipped |
| `state_file` | `state/prices.json` | Where history and alert markers are kept, relative to `config.yml` |

The schedule is in [`.github/workflows/run.yml`](.github/workflows/run.yml) (`cron: "23 */6 * * *"`, UTC). Unknown keys and invalid values stop the run with a clear error, so a typo cannot fail silently.

## Cost

Each run makes **one API request per watchlist item**. The response already holds everything an alert uses.

With the default config (3 items, every 6 hours), that is **3 requests per run, 12 per day, about 360 per 30 days**. Retries after a blocked or timed-out call can add a few on a bad day. `--dry-run` makes the same requests as a real run. `status` and `test-destinations` make none. To spend less, check less often (for example `cron: "23 7 * * *"` for once a day) or trim the watchlist.

## Adding another destination

Destinations live behind one small interface in [`src/amazon_price_drop_alerts/sinks.py`](src/amazon_price_drop_alerts/sinks.py). A sink has a `name`, `send(alerts)` and `send_text(text)`, and raises `DeliveryError` on failure. For a service that takes text over a webhook, subclass `TextSink`. Here is Google Chat:

```python
from amazon_price_drop_alerts import messages
from amazon_price_drop_alerts.sinks import REGISTRY, SinkSpec, TextSink


class GoogleChatSink(TextSink):
    name = "google_chat"
    style = messages.PLAIN
    limit = 4000

    def __init__(self, webhook_url, http):
        super().__init__(http)
        self.webhook_url = webhook_url

    def url(self):
        return self.webhook_url

    def payload(self, text):
        return {"text": text}


REGISTRY["google_chat"] = SinkSpec(
    env=("GOOGLE_CHAT_WEBHOOK_URL",),
    build=lambda env, http: GoogleChatSink(env["GOOGLE_CHAT_WEBHOOK_URL"], http),
)
```

Then add `"google_chat"` to `DESTINATIONS` in `config.py`, list it under `destinations` in `config.yml`, and pass the secret to the run step in `run.yml`. For anything else (a database, a spreadsheet), implement `send(alerts)` and use each alert's fields (`alert.to_dict()`).

## Development

```bash
make install    # pip install -e ".[dev]"
make lint       # ruff check + ruff format --check
make test       # offline tests: the SDK and every destination are mocked, no API credit used
make dry-run    # real prices, nothing sent
```

The tests cover the alert rules (target, median drop, once-per-price-level, re-arming, back in stock, currency change), two runs in a row delivering only new alerts, each destination's message format and payload, config validation and the CLI. CI runs them on Python 3.11 and 3.13.

## Links

- [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos): the scraping API behind this repo
- [Documentation](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
- [Amazon product API](https://docs.scrapeunblocker.com/plugins/amazon?utm_source=github&utm_medium=integration&utm_campaign=example-repos): every field the product endpoint returns
- [Python SDK](https://docs.scrapeunblocker.com/sdks/python?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
- Want the raw data instead of alerts? [amazon-scraper](https://github.com/ScrapeUnblocker/amazon-scraper) scrapes Amazon search results and product data across 20 marketplaces.

## License

[MIT](LICENSE). Copyright (c) 2026 ScrapeUnblocker.
