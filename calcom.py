"""Cal.com API v2: available slots and booking creation for a public event type.

Availability comes from Cal.com, so the owner's Cal.com schedule, buffers, limits and
connected-calendar conflicts all apply. No API key is required for a public event type; set
CALCOM_API_KEY to authenticate anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from config import Settings

BASE = "https://api.cal.com/v2"
SLOTS_VERSION = "2024-09-04"
BOOKINGS_VERSION = "2026-02-25"
CANCEL_VERSION = "2024-08-13"


class CalcomError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"Cal.com {status}: {str(body)[:300]}")
        self.status = status
        self.body = body


@dataclass(frozen=True)
class CalSlot:
    start: datetime  # tz-aware

    def label(self, tz: ZoneInfo) -> str:
        s = self.start.astimezone(tz)
        hour = s.strftime("%I").lstrip("0")
        return f"{s.strftime('%A %B')} {s.day} at {hour}:{s.strftime('%M %p')}"

    def to_dict(self, tz: ZoneInfo, tz_spoken: str) -> dict[str, str]:
        return {"start_iso": self.start.isoformat(), "label": f"{self.label(tz)} {tz_spoken}"}


def select_slots(
    slots: list[CalSlot],
    *,
    now: datetime,
    min_notice_hours: int,
    caller_tz: ZoneInfo,
    earliest_hour: int | None = None,
    latest_hour: int | None = None,
    meeting_minutes: int = 30,
    limit: int = 5,
    per_day: int = 2,
) -> list[CalSlot]:
    """Apply the caller's window and spread picks across days. Pure, for tests."""
    earliest_start = now + timedelta(hours=min_notice_hours)
    out: list[CalSlot] = []
    per_day_count: dict[date, int] = {}
    for s in sorted(slots, key=lambda x: x.start):
        if s.start < earliest_start:
            continue
        local = s.start.astimezone(caller_tz)
        if earliest_hour is not None and local.hour < earliest_hour:
            continue
        if latest_hour is not None:
            end = local + timedelta(minutes=meeting_minutes)
            if end.hour * 60 + end.minute > latest_hour * 60 and end.date() == local.date():
                continue
        d = local.date()
        if per_day_count.get(d, 0) >= per_day:
            continue
        per_day_count[d] = per_day_count.get(d, 0) + 1
        out.append(s)
        if len(out) >= limit:
            break
    return out


class Calcom:
    def __init__(self, settings: Settings):
        self.s = settings

    def _headers(self, version: str) -> dict[str, str]:
        h = {"cal-api-version": version, "Content-Type": "application/json"}
        if self.s.calcom_api_key:
            h["Authorization"] = f"Bearer {self.s.calcom_api_key}"
        return h

    async def _request(self, method: str, path: str, version: str, **kw: Any) -> Any:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.request(method, f"{BASE}{path}", headers=self._headers(version), **kw) as r:
                try:
                    body = await r.json()
                except Exception:
                    body = await r.text()
                if r.status >= 400:
                    raise CalcomError(r.status, body)
                return body

    async def slots(self, start: date, end: date, tz: ZoneInfo) -> list[CalSlot]:
        params = {
            "username": self.s.calcom_username,
            "eventTypeSlug": self.s.calcom_event_slug,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeZone": str(tz),
        }
        body = await self._request("GET", "/slots", SLOTS_VERSION, params=params)
        out: list[CalSlot] = []
        for _day, items in (body.get("data") or {}).items():
            for it in items:
                raw = it["start"] if isinstance(it, dict) else it
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
                out.append(CalSlot(dt))
        return out

    async def is_available(self, start: datetime, tz: ZoneInfo) -> bool:
        day = start.astimezone(tz).date()
        slots = await self.slots(day, day, tz)
        key = start.astimezone(timezone.utc).replace(microsecond=0)
        return any(s.start.astimezone(timezone.utc).replace(microsecond=0) == key for s in slots)

    async def book(
        self,
        *,
        start: datetime,
        name: str,
        email: str,
        tz: ZoneInfo,
        phone: str | None,
        notes: str,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "start": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "eventTypeSlug": self.s.calcom_event_slug,
            "username": self.s.calcom_username,
            "attendee": {"name": name, "email": email, "timeZone": str(tz), "language": "en"},
            "bookingFieldsResponses": {"notes": notes},
            "metadata": {k: str(v)[:500] for k, v in (metadata or {}).items()},
        }
        if phone and phone.startswith("+"):
            body["attendee"]["phoneNumber"] = phone
        resp = await self._request("POST", "/bookings", BOOKINGS_VERSION, json=body)
        return resp.get("data", resp)

    async def cancel(self, uid: str, reason: str = "test") -> Any:
        return await self._request(
            "POST", f"/bookings/{uid}/cancel", CANCEL_VERSION, json={"cancellationReason": reason}
        )


def meeting_url(booking: dict[str, Any]) -> str | None:
    loc = booking.get("location")
    if isinstance(loc, str) and loc.startswith("http"):
        return loc
    return booking.get("meetingUrl")
