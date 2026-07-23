"""Web Push 구독·주의보 스냅샷 저장."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
SUBSCRIPTIONS_FILE = DATA_DIR / "push_subscriptions.json"
ALERT_SNAPSHOT_FILE = DATA_DIR / "alert_snapshot.json"
LAST_PUSH_FILE = DATA_DIR / "last_push_state.json"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, payload) -> None:
    _ensure_data_dir()
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_subscriptions() -> list[dict]:
    data = _read_json(SUBSCRIPTIONS_FILE, {"subscriptions": []})
    return list(data.get("subscriptions") or [])


def save_subscriptions(subscriptions: list[dict]) -> None:
    _write_json(
        SUBSCRIPTIONS_FILE,
        {"updated_at": utc_now_iso(), "subscriptions": subscriptions},
    )


def upsert_subscription(subscription: dict) -> None:
    endpoint = subscription.get("endpoint")
    if not endpoint:
        return
    items = list_subscriptions()
    filtered = [item for item in items if item.get("endpoint") != endpoint]
    filtered.append({**subscription, "updated_at": utc_now_iso()})
    save_subscriptions(filtered)


def remove_subscription(endpoint: str) -> None:
    items = [item for item in list_subscriptions() if item.get("endpoint") != endpoint]
    save_subscriptions(items)


def save_alert_snapshot(snapshot: dict) -> dict:
    payload = {**snapshot, "updated_at": utc_now_iso()}
    _write_json(ALERT_SNAPSHOT_FILE, payload)
    return payload


def get_alert_snapshot() -> dict | None:
    data = _read_json(ALERT_SNAPSHOT_FILE, None)
    return data if isinstance(data, dict) else None


def get_last_push_state() -> dict:
    return _read_json(LAST_PUSH_FILE, {})


def save_last_push_state(state: dict) -> None:
    _write_json(LAST_PUSH_FILE, {**state, "updated_at": utc_now_iso()})
