from datetime import datetime

import pytest

from config import Settings
from prompts import backend_instructions


def test_default_is_email_mode():
    s = Settings.from_env({})
    assert s.contact_mode == "email"
    text = backend_instructions(s, datetime(2026, 11, 12, tzinfo=s.owner_tz), "+1")
    assert "Call confirm_email with what you heard" in text


def test_phone_mode_prompt_never_asks_email():
    s = Settings.from_env({"CONTACT_MODE": "phone", "CALCOM_USERNAME": "u"})
    text = backend_instructions(s, datetime(2026, 11, 12, tzinfo=s.owner_tz), "+1")
    assert "Do NOT ask for an email" in text
    assert "Is that okay?" in text
    assert "text with the meeting link" in text


def test_bad_contact_mode():
    with pytest.raises(ValueError):
        Settings.from_env({"CONTACT_MODE": "sms"})
