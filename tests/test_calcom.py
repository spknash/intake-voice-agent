from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from calcom import CalSlot, meeting_url, select_slots

NY = ZoneInfo("America/New_York")
LA = ZoneInfo("America/Los_Angeles")


def _slots(day: int, hours: list[float]) -> list[CalSlot]:
    out = []
    for h in hours:
        out.append(CalSlot(datetime(2026, 11, day, int(h), int((h % 1) * 60), tzinfo=NY)))
    return out


def test_select_spreads_across_days_and_limits():
    slots = _slots(13, [14.5, 15, 15.5, 16]) + _slots(14, [11, 11.5, 12]) + _slots(15, [11])
    now = datetime(2026, 11, 12, 12, 0, tzinfo=NY)
    picks = select_slots(slots, now=now, min_notice_hours=12, caller_tz=NY)
    assert len(picks) == 5
    assert [p.start.day for p in picks] == [13, 13, 14, 14, 15]


def test_select_respects_min_notice():
    slots = _slots(13, [14.5, 15])
    now = datetime(2026, 11, 13, 10, 0, tzinfo=NY)
    assert select_slots(slots, now=now, min_notice_hours=12, caller_tz=NY) == []
    assert len(select_slots(slots, now=now, min_notice_hours=1, caller_tz=NY)) == 2


def test_select_applies_caller_window_in_caller_tz():
    # 2:30 PM / 3 PM Eastern == 11:30 AM / 12 PM Pacific
    slots = _slots(13, [14.5, 15, 15.5])
    now = datetime(2026, 11, 12, 12, 0, tzinfo=NY)
    picks = select_slots(slots, now=now, min_notice_hours=0, caller_tz=LA, latest_hour=12, per_day=5)
    assert [p.start.hour + p.start.minute / 60 for p in picks] == [14.5]


def test_slot_label_and_dict():
    s = CalSlot(datetime(2026, 11, 13, 15, 0, tzinfo=NY))
    d = s.to_dict(NY, "Eastern")
    assert d["label"] == "Friday November 13 at 3:00 PM Eastern"
    assert d["start_iso"].startswith("2026-11-13T15:00:00")


def test_meeting_url_prefers_location():
    assert meeting_url({"location": "https://meet.google.com/x", "meetingUrl": "y"}) == "https://meet.google.com/x"
    assert meeting_url({"location": "integrations:daily", "meetingUrl": "https://cal.com/video/abc"}) == "https://cal.com/video/abc"
