"""Per-call trace files and the follow-up request log.

One JSON file per call in TRACES_DIR, plus requests.jsonl for manual follow-up.
The 7-day booking limit is answered from these files so there is no database yet.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import Settings, normalize_phone

REQUESTS_FILE = "requests.jsonl"


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:80]


def write_trace(settings: Settings, room: str, payload: dict[str, Any]) -> Path:
    settings.traces_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = settings.traces_dir / f"{stamp}_{_safe(room)}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def append_request(settings: Settings, record: dict[str, Any]) -> None:
    settings.traces_dir.mkdir(parents=True, exist_ok=True)
    record = {"logged_at": datetime.now(timezone.utc).isoformat(), **record}
    with (settings.traces_dir / REQUESTS_FILE).open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def recent_booking(settings: Settings, phone: str, now: datetime | None = None) -> dict | None:
    """Return the most recent booked trace for this phone within the cooldown, or None."""
    if not settings.traces_dir.exists() or not phone:
        return None
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings.booking_cooldown_days)
    phone = normalize_phone(phone)
    for path in sorted(settings.traces_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("outcome") != "booked":
            continue
        if normalize_phone(str(data.get("caller_phone", ""))) != phone:
            continue
        started = data.get("started_at")
        try:
            when = datetime.fromisoformat(started) if started else None
        except ValueError:
            when = None
        if when is None:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= cutoff:
            return data
    return None
