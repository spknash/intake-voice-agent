from config import Settings
from sms import Confirmation, Twilio


def test_confirmation_text():
    c = Confirmation("Suhaas", "Friday November 13 at 3:00 PM Eastern", "https://meet.google.com/abc", "https://cal.com/booking/u1")
    assert c.text() == (
        "Booked: Friday November 13 at 3:00 PM Eastern with Suhaas.\n"
        "Join: https://meet.google.com/abc\n"
        "Change or cancel: https://cal.com/booking/u1"
    )
    assert Confirmation("S", "x", None, None).text() == "Booked: x with S."


def test_twilio_enabled_requires_all_settings():
    assert not Twilio(Settings.from_env({})).enabled
    s = Settings.from_env({
        "TWILIO_ACCOUNT_SID": "AC1", "TWILIO_API_KEY_SID": "SK1", "TWILIO_API_KEY_SECRET": "x", "SMS_FROM": "+1 (855) 555-0100",
    })
    assert Twilio(s).enabled
    assert s.sms_from == "+18555550100"
