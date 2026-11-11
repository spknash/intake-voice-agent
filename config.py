"""Availability and runtime settings, loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

_DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_days(spec: str) -> set[int]:
    """Parse 'Mon-Fri' or 'Mon,Wed,Fri' into weekday numbers (Mon=0)."""
    spec = spec.strip().lower()
    if not spec:
        return set(range(5))
    days: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = [p.strip()[:3] for p in part.split("-", 1)]
            ia, ib = _DAY_NAMES.index(a), _DAY_NAMES.index(b)
            if ia <= ib:
                days.update(range(ia, ib + 1))
            else:
                days.update(range(ia, 7))
                days.update(range(0, ib + 1))
        else:
            days.add(_DAY_NAMES.index(part[:3]))
    return days


def _parse_hours(spec: str) -> tuple[int, int]:
    """Parse '10-18' into (10, 18). End is exclusive."""
    a, b = spec.split("-", 1)
    start, end = int(a), int(b)
    if not (0 <= start < end <= 24):
        raise ValueError(f"BOOKABLE_HOURS out of range: {spec}")
    return start, end


def _parse_blocklist(spec: str) -> set[str]:
    return {normalize_phone(p) for p in spec.split(",") if p.strip()}


def normalize_phone(raw: str) -> str:
    """Keep digits only, plus a leading '+' if present, so comparisons are stable."""
    raw = raw.strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw
    return "+" + digits


@dataclass(frozen=True)
class Settings:
    owner_name: str = "Suhaas"
    owner_tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("America/New_York"))
    bookable_days: set[int] = field(default_factory=lambda: set(range(5)))
    bookable_hours: tuple[int, int] = (10, 18)
    meeting_minutes: int = 30
    buffer_minutes: int = 15
    max_per_day: int = 4
    min_notice_hours: int = 12
    horizon_days: int = 14
    mode: str = "live"
    max_call_seconds: int = 8 * 60
    booking_cooldown_days: int = 7
    blocklist: set[str] = field(default_factory=set)
    traces_dir: Path = field(default_factory=lambda: Path("traces"))
    calendar_id: str = "primary"
    token_path: Path = field(default_factory=lambda: Path("token.json"))
    credentials_path: Path = field(default_factory=lambda: Path("credentials.json"))

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        e = os.environ if env is None else env
        mode = e.get("MODE", "live").strip().lower()
        if mode not in {"live", "realtime"}:
            raise ValueError(f"MODE must be 'live' or 'realtime', got {mode!r}")
        return cls(
            owner_name=e.get("OWNER_NAME", "Suhaas"),
            owner_tz=ZoneInfo(e.get("OWNER_TZ", "America/New_York")),
            bookable_days=_parse_days(e.get("BOOKABLE_DAYS", "Mon-Fri")),
            bookable_hours=_parse_hours(e.get("BOOKABLE_HOURS", "10-18")),
            meeting_minutes=int(e.get("MEETING_MINUTES", "30")),
            buffer_minutes=int(e.get("BUFFER_MINUTES", "15")),
            max_per_day=int(e.get("MAX_PER_DAY", "4")),
            min_notice_hours=int(e.get("MIN_NOTICE_HOURS", "12")),
            horizon_days=int(e.get("HORIZON_DAYS", "14")),
            mode=mode,
            max_call_seconds=int(e.get("MAX_CALL_SECONDS", str(8 * 60))),
            booking_cooldown_days=int(e.get("BOOKING_COOLDOWN_DAYS", "7")),
            blocklist=_parse_blocklist(e.get("BLOCKLIST", "")),
            traces_dir=Path(e.get("TRACES_DIR", "traces")),
            calendar_id=e.get("GOOGLE_CALENDAR_ID", "primary"),
            token_path=Path(e.get("GOOGLE_TOKEN_PATH", "token.json")),
            credentials_path=Path(e.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")),
        )
