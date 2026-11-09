import httpx
import pytest
from conftest import FakeResponse, RecordingHttp, make_alert

from amazon_price_drop_alerts.sinks import (
    DeliveryError,
    DiscordSink,
    SlackSink,
    TelegramSink,
    WebhookSink,
    build_sinks,
    post_json,
)

SLACK_URL = "https://hooks.slack.com/services/T000/B000/XXXX"
DISCORD_URL = "https://discord.com/api/webhooks/123/abc"


def test_slack_payload():
    http = RecordingHttp()
    SlackSink(SLACK_URL, http).send([make_alert()])
    [(url, payload)] = http.posts
    assert url == SLACK_URL
    assert payload["unfurl_links"] is False
    assert payload["text"].startswith("*Amazon price alert: 1 item on your watchlist*")
    assert "<https://www.amazon.com/dp/B09XS7JWHH|Sony WH-1000XM5 headphones>" in payload["text"]


def test_discord_payload_and_chunking():
    http = RecordingHttp()
    DiscordSink(DISCORD_URL, http).send([make_alert(key=str(i)) for i in range(12)])
    assert len(http.posts) > 1
    for url, payload in http.posts:
        assert url == DISCORD_URL
        assert len(payload["content"]) <= 1900
        assert payload["allowed_mentions"] == {"parse": []}
        assert payload["flags"] == 4


def test_telegram_payload():
    http = RecordingHttp()
    TelegramSink("123:abc", "-1001", http).send([make_alert()])
    [(url, payload)] = http.posts
    assert url == "https://api.telegram.org/bot123:abc/sendMessage"
    assert payload["chat_id"] == "-1001"
    assert payload["parse_mode"] == "HTML"
    assert payload["text"].startswith("<b>Amazon price alert")


def test_webhook_payload_is_structured():
    http = RecordingHttp()
    WebhookSink("https://example.com/hook", http).send([make_alert()])
    [(_, payload)] = http.posts
    assert payload["source"] == "amazon-price-drop-alerts"
    assert payload["text"].startswith("Amazon price alert: 1 item")
    [alert] = payload["alerts"]
    assert alert["price"] == 169.0
    assert alert["reasons"] == ["target", "drop", "lowest"]


def test_http_error_status_raises():
    http = RecordingHttp([FakeResponse(status_code=404, text="no_service")])
    with pytest.raises(DeliveryError, match="slack: HTTP 404 no_service"):
        SlackSink(SLACK_URL, http).send([make_alert()])


def test_network_error_does_not_leak_url():
    http = RecordingHttp([httpx.ConnectError("boom")])
    sink = TelegramSink("123:secret-token", "1", http)
    with pytest.raises(DeliveryError) as info:
        sink.send_text("hello")
    assert "secret-token" not in str(info.value)
    assert "ConnectError" in str(info.value)


def test_rate_limit_is_retried_once():
    waits = []
    http = RecordingHttp([FakeResponse(status_code=429, headers={"Retry-After": "3"})])
    post_json(http, DISCORD_URL, {"content": "x"}, sink="discord", sleep=waits.append)
    assert waits == [3.0]
    assert len(http.posts) == 2


def test_build_sinks_skips_missing_secrets():
    env = {
        "SLACK_WEBHOOK_URL": f" {SLACK_URL} ",
        "DISCORD_WEBHOOK_URL": "",
        "TELEGRAM_BOT_TOKEN": "123:abc",  # chat id missing
    }
    sinks, skipped = build_sinks(["slack", "discord", "telegram", "webhook"], env, RecordingHttp())
    assert [s.name for s in sinks] == ["slack"]
    assert sinks[0].webhook_url == SLACK_URL
    assert skipped == ["discord", "telegram", "webhook"]


def test_build_sinks_respects_config_list():
    env = {"SLACK_WEBHOOK_URL": SLACK_URL, "ALERT_WEBHOOK_URL": "https://example.com/h"}
    sinks, skipped = build_sinks(["webhook"], env, RecordingHttp())
    assert [s.name for s in sinks] == ["webhook"]
    assert skipped == []


def test_telegram_api_base_override():
    env = {
        "TELEGRAM_BOT_TOKEN": "1:a",
        "TELEGRAM_CHAT_ID": "2",
        "TELEGRAM_API_BASE": "https://tg.example.com/",
    }
    [sink], _ = build_sinks(["telegram"], env, RecordingHttp())
    assert sink.url() == "https://tg.example.com/bot1:a/sendMessage"
