import io
from datetime import date

import pytest
from conftest import FakeClient, FakeResponse, RecordingHttp, product_payload

from amazon_price_drop_alerts.cli import build_parser, load_env_file, main

CONFIG = """
watchlist:
  - asin: B09XS7JWHH
    name: Sony WH-1000XM5 headphones
    target_price: 210
  - asin: B0CFPJYX7P
    name: Kindle Paperwhite
    target_price: 149
destinations: [slack, webhook]
state_file: state/prices.json
"""
ENV = {
    "SCRAPEUNBLOCKER_KEY": "test-key",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T000/B000/XXXX",
}
TODAY = date(2026, 11, 9)


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def responses():
    return {
        "B09XS7JWHH": product_payload("B09XS7JWHH", 199.95),
        "B0CFPJYX7P": product_payload("B0CFPJYX7P", 199.99),
    }


def invoke(args, *, client=None, http=None, env=None, today=TODAY):
    out = io.StringIO()
    code = main(
        [*args, "--env-file", "does-not-exist.env"],
        environ=dict(ENV if env is None else env),
        client_factory=(lambda: client) if client else None,
        http_factory=lambda: http or RecordingHttp(),
        today=today,
        out=out,
    )
    return code, out.getvalue()


def test_parser_defaults():
    args = build_parser().parse_args(["run"])
    assert args.command == "run"
    assert args.config == "config.yml"
    assert args.dry_run is False
    assert args.env_file == ".env"


def test_parser_options():
    args = build_parser().parse_args(["run", "--dry-run", "-c", "other.yml", "-v"])
    assert args.dry_run and args.verbose and args.config == "other.yml"
    assert build_parser().parse_args(["status"]).command == "status"
    assert build_parser().parse_args(["test-destinations"]).command == "test-destinations"


def test_parser_requires_a_command():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_two_runs_deliver_only_new_alerts(config_path):
    http = RecordingHttp()
    code, out = invoke(["run", "-c", str(config_path)], client=FakeClient(responses()), http=http)
    assert code == 0
    assert "Delivered 1 alert(s) to slack." in out
    [(url, payload)] = http.posts
    assert url == ENV["SLACK_WEBHOOK_URL"]
    assert "Sony WH-1000XM5 headphones" in payload["text"]
    assert "at or below your target of $210.00" in payload["text"]
    assert "Kindle" not in payload["text"]
    state_file = config_path.parent / "state" / "prices.json"
    assert state_file.exists()

    # Same prices again: nothing is delivered and the state file does not change.
    http2 = RecordingHttp()
    code, out = invoke(["run", "-c", str(config_path)], client=FakeClient(responses()), http=http2)
    assert code == 0
    assert http2.posts == []
    assert "Nothing new to deliver." in out
    assert "State unchanged" in out


def test_dry_run_sends_and_saves_nothing(config_path):
    http = RecordingHttp()
    client = FakeClient(responses())
    code, out = invoke(["run", "--dry-run", "-c", str(config_path)], client=client, http=http)
    assert code == 0
    assert http.posts == []
    assert not (config_path.parent / "state" / "prices.json").exists()
    assert "Dry run: 1 alert(s). Nothing was sent or saved." in out
    assert "--- slack ---" in out
    assert "*<https://www.amazon.com/dp/B09XS7JWHH|Sony WH-1000XM5 headphones>*" in out
    assert len(client.calls) == 2


def test_failed_delivery_is_retried_next_run(config_path):
    broken = RecordingHttp([FakeResponse(status_code=500, text="down")])
    code, _ = invoke(["run", "-c", str(config_path)], client=FakeClient(responses()), http=broken)
    assert code == 1
    http = RecordingHttp()
    code, out = invoke(["run", "-c", str(config_path)], client=FakeClient(responses()), http=http)
    assert code == 0
    assert len(http.posts) == 1  # the alert that failed before goes out now


def test_missing_api_key(config_path):
    code, _ = invoke(["run", "-c", str(config_path)], env={"SLACK_WEBHOOK_URL": "x"})
    assert code == 2


def test_no_destination_configured(config_path, capsys):
    code, _ = invoke(["run", "-c", str(config_path)], env={"SCRAPEUNBLOCKER_KEY": "k"})
    assert code == 2
    assert "SLACK_WEBHOOK_URL (slack)" in capsys.readouterr().err


def test_dry_run_works_without_destinations(config_path):
    client = FakeClient(responses())
    code, out = invoke(
        ["run", "--dry-run", "-c", str(config_path)],
        client=client,
        env={"SCRAPEUNBLOCKER_KEY": "k"},
    )
    assert code == 0
    assert "No destination secrets are set" in out
    assert "Sony WH-1000XM5 headphones\nhttps://www.amazon.com/dp/B09XS7JWHH" in out


def test_test_destinations(config_path):
    http = RecordingHttp()
    code, out = invoke(["test-destinations", "-c", str(config_path)], http=http)
    assert code == 0
    assert "slack     ok" in out
    assert "webhook   skipped" in out
    assert "is connected" in http.posts[0][1]["text"]


def test_status_after_a_run(config_path):
    invoke(["run", "-c", str(config_path)], client=FakeClient(responses()))
    code, out = invoke(["status", "-c", str(config_path)])
    assert code == 0
    assert "amazon.com:B09XS7JWHH" in out
    assert "last price      $199.95" in out
    assert "last alert at   $199.95" in out
    assert "target          $149.00" in out


def test_bad_config_exit_code(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("watchlist: []\n", encoding="utf-8")
    code, _ = invoke(["status", "-c", str(path)])
    assert code == 2


def test_env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# comment\nSCRAPEUNBLOCKER_KEY=from-file\nexport SLACK_WEBHOOK_URL='https://x'\n"
        "ALREADY=file\n",
        encoding="utf-8",
    )
    env = {"ALREADY": "real"}
    load_env_file(path, env)
    assert env == {
        "SCRAPEUNBLOCKER_KEY": "from-file",
        "SLACK_WEBHOOK_URL": "https://x",
        "ALREADY": "real",
    }
