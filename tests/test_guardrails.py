import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("LIVEKIT_URL", "wss://test")
os.environ.setdefault("LIVEKIT_API_KEY", "a")
os.environ.setdefault("LIVEKIT_API_SECRET", "b")

from livekit.agents import ToolError  # noqa: E402

from agent import CallState, _slot_key, assert_email_checked, assert_offered  # noqa: E402


def _state() -> CallState:
    return CallState(room="r", caller_phone="+1", started_at=datetime.now(timezone.utc))


def test_booking_requires_offered_slot():
    s = _state()
    t = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
    with pytest.raises(ToolError):
        assert_offered(s, t)
    s.offered_slots.add(_slot_key(t))
    assert_offered(s, t)  # no raise


def test_booking_requires_checked_email():
    s = _state()
    with pytest.raises(ToolError):
        assert_email_checked(s, "jane@acme.com")
    s.checked_emails.add("jane@acme.com")
    assert_email_checked(s, " Jane@Acme.com ")  # case and whitespace insensitive
