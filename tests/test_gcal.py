from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import Settings
from gcal import Busy, generate_slots

NY = ZoneInfo("America/New_York")
LA = ZoneInfo("America/Los_Angeles")

# Monday 2026-11-16 09:00 New York
NOW = datetime(2026, 11, 16, 9, 0, tzinfo=NY)


def settings(**over) -> Settings:
    return Settings.from_env({"MIN_NOTICE_HOURS": "0", **over})


def test_slots_respect_bookable_days_and_hours():
    slots = generate_slots(
        settings=settings(),
        busy=[],
        now=NOW,
        start_date=date(2026, 11, 21),  # Saturday
        end_date=date(2026, 11, 23),  # Monday
        caller_tz=NY,
        limit=10,
        per_day=10,
    )
    assert slots, "expected Monday slots"
    assert all(s.start.date() == date(2026, 11, 23) for s in slots)
    assert all(10 <= s.start.hour < 18 for s in slots)
    assert slots[-1].end.hour <= 18


def test_busy_slot_and_buffer_never_offered():
    busy = [Busy(datetime(2026, 11, 17, 13, 0, tzinfo=NY), datetime(2026, 11, 17, 14, 0, tzinfo=NY))]
    slots = generate_slots(
        settings=settings(),
        busy=busy,
        now=NOW,
        start_date=date(2026, 11, 17),
        end_date=date(2026, 11, 17),
        caller_tz=NY,
        limit=20,
        per_day=20,
    )
    starts = {s.start.hour + s.start.minute / 60 for s in slots}
    # 12:30 would end 13:00 and violate the 15-minute buffer; 14:00 starts inside the buffer.
    for blocked in (12.5, 13.0, 13.5, 14.0):
        assert blocked not in starts
    assert 12.0 in starts and 14.5 in starts


def test_min_notice_applies():
    s = Settings.from_env({"MIN_NOTICE_HOURS": "12"})
    slots = generate_slots(
        settings=s,
        busy=[],
        now=NOW,
        start_date=date(2026, 11, 16),
        end_date=date(2026, 11, 16),
        caller_tz=NY,
        limit=20,
        per_day=20,
    )
    assert slots == []  # everything today is within 12 hours of 09:00 (ends 18:00)


def test_max_per_day_blocks_full_day():
    day = date(2026, 11, 18)
    busy = [
        Busy(datetime(2026, 11, 18, h, 0, tzinfo=NY), datetime(2026, 11, 18, h, 30, tzinfo=NY))
        for h in (10, 11, 12, 13)
    ]
    slots = generate_slots(
        settings=settings(),
        busy=busy,
        now=NOW,
        start_date=day,
        end_date=day,
        caller_tz=NY,
        limit=20,
        per_day=20,
    )
    assert slots == []


def test_caller_window_in_caller_timezone():
    # Caller in LA wants 9am-12pm their time => 12pm-3pm NY
    slots = generate_slots(
        settings=settings(),
        busy=[],
        now=NOW,
        start_date=date(2026, 11, 17),
        end_date=date(2026, 11, 17),
        caller_tz=LA,
        earliest_hour=9,
        latest_hour=12,
        limit=20,
        per_day=20,
    )
    assert slots
    for s in slots:
        local = s.start.astimezone(LA)
        assert 9 <= local.hour and (local + timedelta(minutes=30)).hour * 60 + (local + timedelta(minutes=30)).minute <= 12 * 60
    assert "PST" in slots[0].label(LA)


def test_horizon_and_limit():
    slots = generate_slots(
        settings=settings(HORIZON_DAYS="3"),
        busy=[],
        now=NOW,
        start_date=date(2026, 11, 16),
        end_date=date(2026, 12, 16),
        caller_tz=NY,
    )
    assert len(slots) <= 5
    assert all(s.start <= NOW + timedelta(days=3) for s in slots)
    # default spreads 2 per day
    assert len({s.start.date() for s in slots}) >= 2
