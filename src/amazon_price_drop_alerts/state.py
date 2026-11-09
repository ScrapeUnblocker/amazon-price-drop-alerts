"""What has been seen and delivered, kept in one JSON file.

The scheduled GitHub Actions workflow commits this file back to the repo after each
run, so the price history and "already alerted" markers survive between runs. Prices
are stored once per day per item, so the file only changes when a price moves or a new
day starts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATE_VERSION = 1


class StateError(ValueError):
    """The state file exists but cannot be read."""


def load_state(path: str | Path) -> dict[str, dict[str, Any]]:
    """Return ``{item_key: item_state}``; an empty dict when there is no state yet."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read state file {path}: {exc}") from None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, dict):
        raise StateError(f"state file {path} has no 'items' mapping")
    return items


def dump_state(items: dict[str, dict[str, Any]]) -> str:
    payload = {"version": STATE_VERSION, "items": dict(sorted(items.items()))}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def save_state(path: str | Path, items: dict[str, dict[str, Any]]) -> bool:
    """Write the state atomically. Returns False when the file already had this content."""
    path = Path(path)
    text = dump_state(items)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return True
