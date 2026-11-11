import json
from datetime import datetime, timedelta, timezone

from config import Settings, normalize_phone
from traces import append_request, recent_booking, write_trace


def test_normalize_phone():
    assert normalize_phone("+1 (555) 123-4567") == "+15551234567"
    assert normalize_phone("15551234567") == "+15551234567"


def test_recent_booking_within_cooldown(tmp_path):
    s = Settings.from_env({"TRACES_DIR": str(tmp_path)})
    now = datetime.now(timezone.utc)
    write_trace(s, "room-a", {"outcome": "booked", "caller_phone": "+15551234567", "started_at": (now - timedelta(days=2)).isoformat(), "event_id": "evt1"})
    write_trace(s, "room-b", {"outcome": "abandoned", "caller_phone": "+15550000000", "started_at": now.isoformat()})
    assert recent_booking(s, "+1 (555) 123-4567", now)["event_id"] == "evt1"
    assert recent_booking(s, "+15550000000", now) is None
    assert recent_booking(s, "+15551234567", now + timedelta(days=8)) is None


def test_append_request(tmp_path):
    s = Settings.from_env({"TRACES_DIR": str(tmp_path)})
    append_request(s, {"name": "Jane", "phone": "+1555"})
    lines = (tmp_path / "requests.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["name"] == "Jane"
