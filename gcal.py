"""Google Calendar access: free/busy lookup, slot generation, event creation.

Slot generation is pure (no I/O) so it can be unit tested. The Calendar client wraps the
blocking google-api-python-client in asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build as build_service

from auth_google import load_credentials
from config import Settings


@dataclass(frozen=True)
class Busy:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Slot:
    start: datetime  # tz-aware, in owner tz
    end: datetime

    def label(self, tz: ZoneInfo) -> str:
        """Spoken label in the caller's timezone, e.g. 'Tuesday November 18 at 2:00 PM EST'."""
        s = self.start.astimezone(tz)
        hour = s.strftime("%I").lstrip("0")
        return f"{s.strftime('%A %B')} {s.day} at {hour}:{s.strftime('%M %p %Z')}"

    def to_dict(self, tz: ZoneInfo) -> dict[str, str]:
        return {"start_iso": self.start.isoformat(), "label": self.label(tz)}


def _overlaps(a_start: datetime, a_end: datetime, b: Busy) -> bool:
    return a_start < b.end and b.start < a_end


def generate_slots(
    *,
    settings: Settings,
    busy: list[Busy],
    now: datetime,
    start_date: date,
    end_date: date,
    caller_tz: ZoneInfo,
    earliest_hour: int | None = None,
    latest_hour: int | None = None,
    limit: int = 5,
    per_day: int = 2,
) -> list[Slot]:
    """Generate bookable slots between start_date and end_date inclusive (owner-tz dates).

    Rules applied, in order: bookable weekday, bookable hours, minimum notice, horizon,
    buffer-padded overlap with busy blocks, max bookings per day, and the caller's
    preferred hour window expressed in the caller's timezone.
    """
    tz = settings.owner_tz
    now = now.astimezone(tz)
    earliest_start = now + timedelta(hours=settings.min_notice_hours)
    horizon_end = now + timedelta(days=settings.horizon_days)
    step = timedelta(minutes=settings.meeting_minutes)
    length = timedelta(minutes=settings.meeting_minutes)
    buffer = timedelta(minutes=settings.buffer_minutes)
    open_h, close_h = settings.bookable_hours

    out: list[Slot] = []
    day = max(start_date, now.date())
    while day <= end_date and len(out) < limit:
        if day.weekday() not in settings.bookable_days:
            day += timedelta(days=1)
            continue

        day_start = datetime.combine(day, time(open_h), tzinfo=tz)
        day_end = datetime.combine(day, time(0), tzinfo=tz) + timedelta(hours=close_h)

        busy_today = [
            b
            for b in busy
            if _overlaps(day_start, day_end, Busy(b.start.astimezone(tz), b.end.astimezone(tz)))
        ]
        if len(busy_today) >= settings.max_per_day:
            day += timedelta(days=1)
            continue

        taken_today = 0
        cursor = day_start
        while cursor + length <= day_end and len(out) < limit and taken_today < per_day:
            slot_start, slot_end = cursor, cursor + length
            cursor += step
            if slot_start < earliest_start or slot_start > horizon_end:
                continue
            if any(_overlaps(slot_start - buffer, slot_end + buffer, b) for b in busy):
                continue
            if earliest_hour is not None or latest_hour is not None:
                local = slot_start.astimezone(caller_tz)
                local_end = slot_end.astimezone(caller_tz)
                if earliest_hour is not None and local.hour < earliest_hour:
                    continue
                if latest_hour is not None:
                    # the whole meeting has to finish by latest_hour
                    end_minutes = local_end.hour * 60 + local_end.minute
                    if end_minutes > latest_hour * 60 and not (
                        local_end.date() > local.date()
                    ):
                        continue
            out.append(Slot(slot_start, slot_end))
            taken_today += 1
        day += timedelta(days=1)
    return out


class Calendar:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._service = None

    def _svc(self):
        if self._service is None:
            creds = load_credentials(self.settings)
            self._service = build_service("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    async def freebusy(self, start: datetime, end: datetime) -> list[Busy]:
        def _call() -> list[Busy]:
            body = {
                "timeMin": start.astimezone(timezone.utc).isoformat(),
                "timeMax": end.astimezone(timezone.utc).isoformat(),
                "items": [{"id": self.settings.calendar_id}],
            }
            resp = self._svc().freebusy().query(body=body).execute()
            cal = resp["calendars"][self.settings.calendar_id]
            return [
                Busy(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
                for b in cal.get("busy", [])
            ]

        return await asyncio.to_thread(_call)

    async def is_free(self, start: datetime, end: datetime) -> bool:
        buffer = timedelta(minutes=self.settings.buffer_minutes)
        busy = await self.freebusy(start - buffer, end + buffer)
        return not any(_overlaps(start - buffer, end + buffer, b) for b in busy)

    async def create_event(
        self,
        *,
        start: datetime,
        end: datetime,
        summary: str,
        description: str,
        attendee_email: str,
    ) -> dict:
        def _call() -> dict:
            body = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start.isoformat(), "timeZone": str(self.settings.owner_tz)},
                "end": {"dateTime": end.isoformat(), "timeZone": str(self.settings.owner_tz)},
                "attendees": [{"email": attendee_email}],
                "conferenceData": {
                    "createRequest": {
                        "requestId": f"intake-{int(start.timestamp())}-{abs(hash(attendee_email)) % 10**6}",
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                },
                "reminders": {"useDefault": True},
            }
            return (
                self._svc()
                .events()
                .insert(
                    calendarId=self.settings.calendar_id,
                    body=body,
                    conferenceDataVersion=1,
                    sendUpdates="all",
                )
                .execute()
            )

        return await asyncio.to_thread(_call)


def meet_link(event: dict) -> str | None:
    if link := event.get("hangoutLink"):
        return link
    for ep in event.get("conferenceData", {}).get("entryPoints", []):
        if ep.get("entryPointType") == "video":
            return ep.get("uri")
    return None
