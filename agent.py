"""Phone intake agent that books intro meetings on the owner's Google Calendar.

Run locally:   python agent.py console
Dev worker:    python agent.py dev
Production:    python agent.py start
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    ToolError,
    cli,
    function_tool,
)
from livekit.plugins import silero

import models
import prompts
import traces
from config import Settings, normalize_phone
from emailcheck import check_email
from gcal import Calendar, generate_slots, meet_link

load_dotenv()
logger = logging.getLogger("intake")

settings = Settings.from_env()
calendar = Calendar(settings)

def prewarm(proc: JobProcess) -> None:
    """Runs once per worker process before any job, off the event loop.

    AgentSession needs an explicit VAD so GPT-Live barge-in actually cuts playback.
    """
    proc.userdata["vad"] = silero.VAD.load()


@dataclass
class CallState:
    room: str
    caller_phone: str
    started_at: datetime
    outcome: str = "abandoned"
    event_id: str | None = None
    event_link: str | None = None
    name: str | None = None
    company: str | None = None
    tool_log: list[dict[str, Any]] = field(default_factory=list)

    def log(self, tool: str, **data: Any) -> None:
        self.tool_log.append({"t": time.time(), "tool": tool, **data})


def _parse_date(value: str) -> datetime.date:
    return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name.strip())
    except Exception as exc:
        raise ToolError(
            f"Unknown timezone {name!r}. Use an IANA name like America/Los_Angeles."
        ) from exc


class IntakeAgent(Agent):
    def __init__(self, state: CallState, instructions: str, ctx: JobContext):
        super().__init__(instructions=instructions)
        self.state = state
        self.ctx = ctx

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions="Greet the caller as the scheduling assistant and ask who is calling."
        )

    @function_tool()
    async def find_open_slots(
        self,
        context: RunContext,
        start_date: str,
        end_date: str,
        caller_timezone: str,
        earliest_hour: int | None = None,
        latest_hour: int | None = None,
    ) -> dict[str, Any]:
        """Find open meeting slots on the owner's calendar.

        Args:
            start_date: First date to consider, YYYY-MM-DD, in the owner's timezone.
            end_date: Last date to consider, YYYY-MM-DD, inclusive.
            caller_timezone: IANA timezone of the caller, e.g. America/Chicago.
            earliest_hour: Optional earliest hour (0-23) in the caller's timezone.
            latest_hour: Optional latest hour (0-23) by which the meeting must end, caller's timezone.
        """
        tz = _tz(caller_timezone)
        start = _parse_date(start_date)
        end = _parse_date(end_date)
        if end < start:
            raise ToolError("end_date is before start_date.")
        now = datetime.now(timezone.utc)
        window_start = datetime.combine(start, datetime.min.time(), tzinfo=settings.owner_tz)
        window_end = datetime.combine(end, datetime.min.time(), tzinfo=settings.owner_tz) + timedelta(days=1)
        try:
            busy = await calendar.freebusy(window_start, window_end)
        except Exception as exc:
            logger.exception("freebusy failed")
            raise ToolError("Calendar lookup failed.") from exc
        slots = generate_slots(
            settings=settings,
            busy=busy,
            now=now,
            start_date=start,
            end_date=end,
            caller_tz=tz,
            earliest_hour=earliest_hour,
            latest_hour=latest_hour,
        )
        self.state.log("find_open_slots", start=start_date, end=end_date, tz=caller_timezone, n=len(slots))
        return {
            "slots": [s.to_dict(tz) for s in slots],
            "note": "Offer two or three of these. Speak labels as given; they are already in the caller's timezone."
            if slots
            else "No open slots in that range. Try a wider range once, then log_request.",
        }

    @function_tool()
    async def confirm_email(self, context: RunContext, raw: str) -> dict[str, Any]:
        """Normalize and validate an email address heard from the caller.

        Args:
            raw: The email exactly as transcribed, e.g. "jane dot doe at acme dot com".
        """
        result = await check_email(raw)
        self.state.log("confirm_email", raw=raw, status=result.status, email=result.email)
        return result.to_dict()

    @function_tool()
    async def book_meeting(
        self,
        context: RunContext,
        start_iso: str,
        caller_timezone: str,
        name: str,
        company: str,
        role: str,
        email: str,
        reason: str,
    ) -> dict[str, Any]:
        """Book the meeting on the owner's calendar and invite the caller.

        Args:
            start_iso: The chosen slot's start_iso exactly as returned by find_open_slots.
            caller_timezone: IANA timezone of the caller.
            name: Caller's full name.
            company: Caller's company or organization.
            role: Caller's role or title.
            email: Caller's confirmed email address.
            reason: Why they want to meet, one or two sentences.
        """
        tz = _tz(caller_timezone)
        try:
            start = datetime.fromisoformat(start_iso)
        except ValueError as exc:
            raise ToolError("start_iso is not a valid ISO timestamp.") from exc
        if start.tzinfo is None:
            start = start.replace(tzinfo=settings.owner_tz)
        end = start + timedelta(minutes=settings.meeting_minutes)

        if not await calendar.is_free(start, end):
            self.state.log("book_meeting", result="slot_taken", start=start_iso)
            raise ToolError("That time was just taken. Call find_open_slots again and offer new options.")

        description = (
            f"Booked by phone intake agent.\n\n"
            f"Name: {name}\nCompany: {company}\nRole: {role}\nEmail: {email}\n"
            f"Phone: {self.state.caller_phone or 'unknown'}\n\n"
            f"Reason for meeting:\n{reason}\n"
        )
        try:
            event = await calendar.create_event(
                start=start,
                end=end,
                summary=f"Intro: {name} ({company})",
                description=description,
                attendee_email=email,
            )
        except Exception as exc:
            logger.exception("events.insert failed")
            self.state.log("book_meeting", result="error", error=str(exc))
            raise ToolError("Booking failed.") from exc

        self.state.outcome = "booked"
        self.state.event_id = event.get("id")
        self.state.event_link = meet_link(event)
        self.state.name, self.state.company = name, company
        self.state.log("book_meeting", result="booked", event_id=self.state.event_id)
        local = start.astimezone(tz)
        return {
            "booked": True,
            "when": f"{local.strftime('%A %B')} {local.day} at {local.strftime('%I:%M %p %Z').lstrip('0')}",
            "meet_link": self.state.event_link,
            "note": "Tell the caller the invite with a video link is on its way to their email.",
        }

    @function_tool()
    async def log_request(
        self,
        context: RunContext,
        name: str,
        company: str,
        reason: str,
        preferred_times: str,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Record a meeting request for manual follow-up when booking is not possible.

        Args:
            name: Caller's name as heard.
            company: Caller's company.
            reason: Why they want to meet.
            preferred_times: Their stated availability, in their own words.
            email: Best guess at their email, if any.
        """
        traces.append_request(
            settings,
            {
                "room": self.state.room,
                "phone": self.state.caller_phone,
                "name": name,
                "company": company,
                "reason": reason,
                "preferred_times": preferred_times,
                "email": email,
            },
        )
        if self.state.outcome != "booked":
            self.state.outcome = "logged_request"
        self.state.name, self.state.company = name, company
        self.state.log("log_request", name=name)
        return {"logged": True, "note": f"Tell the caller {settings.owner_name} will follow up directly."}

    @function_tool()
    async def end_call(self, context: RunContext) -> str:
        """End the phone call. Call this only after saying goodbye."""
        self.state.log("end_call")
        await context.wait_for_playout()
        await asyncio.sleep(0.5)
        await self.ctx.delete_room()
        return "Call ended."


async def _enforce_max_duration(ctx: JobContext, session: AgentSession, state: CallState) -> None:
    await asyncio.sleep(settings.max_call_seconds)
    logger.info("max call duration reached", extra={"room": state.room})
    state.log("max_duration")
    try:
        session.generate_reply(
            instructions=(
                "Time is up for this call. In one sentence, apologize, say the caller can call back, "
                "then call end_call."
            )
        )
        await asyncio.sleep(20)
    finally:
        await ctx.delete_room()


server = AgentServer(setup_fnc=prewarm)


@server.rtc_session(agent_name="intake")
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    started = datetime.now(timezone.utc)

    if ctx.is_fake_job():
        caller_phone = "console"
    else:
        try:
            participant = await ctx.wait_for_participant()
        except RuntimeError as exc:
            # room was deleted or the caller hung up before anyone joined
            logger.info("no participant joined: %s", exc)
            return
        caller_phone = normalize_phone(participant.attributes.get("sip.phoneNumber", "") or "")

    state = CallState(room=ctx.room.name, caller_phone=caller_phone, started_at=started)
    ctx.log_context_fields["caller_phone"] = caller_phone
    model_info = models.describe(settings)

    session: AgentSession | None = None

    async def write_trace_on_shutdown(reason: str = "") -> None:
        payload: dict[str, Any] = {
            "room": state.room,
            "caller_phone": state.caller_phone,
            "started_at": state.started_at.isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "shutdown_reason": reason,
            **model_info,
            "outcome": state.outcome,
            "event_id": state.event_id,
            "event_link": state.event_link,
            "caller_name": state.name,
            "caller_company": state.company,
            "tool_log": state.tool_log,
        }
        if session is not None:
            try:
                payload["session_report"] = ctx.make_session_report(session).to_dict()
            except Exception as exc:  # report is best-effort
                payload["session_report_error"] = str(exc)
        # Emit the compact summary first: hosted containers lose traces/ on restart, and
        # stdout is what `lk agent logs` and the LiveKit Cloud dashboard keep.
        logger.info(
            "CALL_SUMMARY %s",
            json.dumps(
                {
                    "room": state.room,
                    "caller_phone": state.caller_phone,
                    "outcome": state.outcome,
                    "duration_s": round((datetime.now(timezone.utc) - state.started_at).total_seconds()),
                    "event_id": state.event_id,
                    "caller_name": state.name,
                    "tools": [t["tool"] for t in state.tool_log],
                    "transcript": _transcript(session),
                },
                default=str,
            ),
        )
        try:
            path = traces.write_trace(settings, state.room, payload)
            logger.info("trace written", extra={"path": str(path), "outcome": state.outcome})
        except Exception:
            logger.exception("failed to write trace file")

    ctx.add_shutdown_callback(write_trace_on_shutdown)

    if caller_phone and caller_phone in settings.blocklist:
        state.outcome = "blocked"
        logger.warning("blocked caller", extra={"caller_phone": caller_phone})
        await ctx.delete_room()
        return

    if caller_phone not in ("", "console") and (prev := traces.recent_booking(settings, caller_phone)):
        state.outcome = "blocked"
        state.log("cooldown", previous_event=prev.get("event_id"))
        logger.info("caller within booking cooldown", extra={"caller_phone": caller_phone})
        await ctx.delete_room()
        return

    now_local = datetime.now(settings.owner_tz)
    voice = prompts.voice_instructions(settings, now_local, caller_phone)
    backend = prompts.backend_instructions(settings, now_local, caller_phone)
    if settings.mode == "realtime":
        # single model: give it both layers
        voice = voice + "\n\n" + backend

    vad = ctx.proc.userdata.get("vad") or silero.VAD.load()
    session = AgentSession(
        llm=models.build(settings, backend),
        vad=vad,
        user_away_timeout=45.0,
    )

    @session.on("error")
    def _on_error(ev: Any) -> None:
        if state.outcome in ("abandoned",):
            state.outcome = "error"
        state.log("session_error", error=str(getattr(ev, "error", ev)))

    timer = asyncio.create_task(_enforce_max_duration(ctx, session, state))
    ctx.add_shutdown_callback(lambda: _cancel(timer))

    await session.start(agent=IntakeAgent(state, voice, ctx), room=ctx.room)


async def _cancel(task: asyncio.Task) -> None:
    task.cancel()


def _transcript(session: AgentSession | None) -> list[dict[str, str]]:
    """Role-tagged text of the conversation, for the stdout call summary."""
    if session is None:
        return []
    out: list[dict[str, str]] = []
    try:
        for item in session.history.items:
            if getattr(item, "type", None) == "message":
                text = item.text_content or ""
                if text.strip():
                    out.append({"role": item.role, "text": text.strip()})
    except Exception:  # best-effort
        pass
    return out


if __name__ == "__main__":
    cli.run_app(server)
