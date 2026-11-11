# Build: Phone intake agent that books meetings with Suhaas

## Goal
A phone number anyone can call. A voice agent finds out who the caller is, why they want to meet, and when they're free. It then books a Google Calendar event on Suhaas's calendar and invites the caller. Every call is logged as a trace for later prompt tuning and post-training.

## Architecture
Two models, split by job:

- **Voice model: OpenAI GPT-Live-1** (`gpt-live-1`). A full-duplex speech-to-speech model that listens and speaks at the same time. It owns the audio: turn-taking, barge-in, backchannels, pacing.
- **Backend reasoning model: GPT-Live's default Responses model** (currently `gpt-5.6-luna` per the LiveKit docs; we do not pin it, so OpenAI's default applies). It owns the thinking: following the intake script, deciding which tools to call, validating emails and dates, composing what the voice model says.

GPT-Live runs in `delegation="responses"` mode (the default). Our `@function_tool` methods run in our own process. Tool results go back to the backend model, which decides what to say next, and the voice model speaks it.

Why this over a single realtime model:
- The original plan's `gpt-realtime` retires on 2027-01-20.
- Reasoning quality comes from a frontier text model instead of whatever is baked into the voice model.
- Full-duplex audio handles interruptions and "uh-huh" far better on a phone line.

Caveats accepted with this choice:
- A full-duplex model cannot speak a script verbatim. Fixed lines (greeting, email readback) are best-effort. We compensate with an explicit `confirm_email` tool so correctness lives in the backend model, not in exact speech.
- Voice and instructions cannot change mid-session.
- We must pass an explicit VAD to `AgentSession` so the framework cuts playback on barge-in.
- `session.say()` raises without a TTS attached, so we never call it. All speech goes through the model.
- Billing: $0.05 per minute of voice, billed per second, plus normal token pricing for the backend model and tools. Not available on the OpenAI Free tier.

## Stack
- Python 3.11+, `livekit-agents[openai]~=1.8` (verified on 1.8.11), `livekit-plugins-silero` for VAD
- LiveKit Cloud project with a LiveKit Phone Number and a dispatch rule to agent name `intake`
- Model: `openai.realtime.GPTLiveModel(voice="marin")` with default `delegation` and default `responses_options["model"]`
  - `responses_options` we do set: `instructions` (backend-side rules), `reasoning={"effort": "medium"}`, `text={"verbosity": "low"}`
  - Behind `MODE=realtime`, fall back to turn-based `openai.realtime.RealtimeModel(model="gpt-realtime-2.1", voice="marin")`. Same tools, same instructions. Useful if full-duplex quirks bite on telephony.
- Google Calendar API (google-api-python-client, google-auth-oauthlib) with OAuth on Suhaas's account and scope `https://www.googleapis.com/auth/calendar`
- Traces: one JSON file per call in `traces/` for now (swap to Postgres later)

## Files
- `agent.py`: entrypoint, agent instructions, tools
- `models.py`: builds the `GPTLiveModel` or `RealtimeModel` from `MODE`
- `gcal.py`: free/busy lookup, slot generation, event creation
- `auth_google.py`: one-time OAuth flow that writes `token.json`
- `config.py`: availability rules loaded from env
- `.env.example`, `requirements.txt`, `README.md`

## Entrypoint (agent.py)
- `server = AgentServer()`, `@server.rtc_session(agent_name="intake")`, `cli.run_app(server)`
- On job start:
  - `await ctx.connect()`, then `participant = await ctx.wait_for_participant()`
  - Read the caller number from `participant.attributes.get("sip.phoneNumber")`
  - Check blocklist and the 7-day booking limit before starting the session. If blocked, play nothing, write a trace with outcome `blocked`, and delete the room.
  - Build `AgentSession(llm=models.build(), vad=silero.VAD.load())`
  - Start the session with an `Agent` whose instructions include today's date, Suhaas's timezone (America/New_York) and the caller's number. The model has no `instructions` parameter; everything goes on the `Agent`.
- Start an 8-minute timer. When it fires, inject a system message telling the agent to wrap up in one sentence, then call `end_call` after 20 seconds regardless.
- `ctx.add_shutdown_callback`: write `ctx.make_session_report(session).to_dict()` plus a call outcome to `traces/<timestamp>_<room>.json`

## Instructions
Two layers. The `Agent` instructions shape the voice. The `responses_options["instructions"]` shape the reasoning.

### Agent instructions (voice layer)
- You are Suhaas's scheduling assistant. Warm, brief, one question per turn.
- Open with a greeting that says who you are and asks who is calling.
- Never invent availability. Only offer times a tool returned.
- Never reveal other events on the calendar.
- Politely decline anything off-topic and steer back to scheduling.

### Backend instructions (reasoning layer)
- Drive this flow in order and track what has been collected:
  1. Caller's name, company, role.
  2. Reason for meeting, plus one follow-up for specifics.
  3. Caller's timezone and free windows. Convert relative dates using today's date.
  4. Call `find_open_slots`, offer 2 or 3 options in the caller's timezone.
  5. Confirm one slot.
  6. Collect email. Call `confirm_email` with your best transcription. If it returns `needs_confirmation`, read the spelled version back and ask for a yes. Retry up to 2 times. If still unconfirmed, call `log_request` instead of booking.
  7. Call `book_meeting`. Read back the confirmed time and say an invite is on its way.
  8. Call `end_call`.
- If no slot fits, call `log_request` and say Suhaas will follow up.
- Keep every spoken reply under two sentences unless listing slots.

## Tools (@function_tool)
All tools run in-process. In `responses` mode the backend model calls them and receives the results.

- `find_open_slots(start_date: str, end_date: str, caller_timezone: str, earliest_hour: int | None, latest_hour: int | None)`
  - Calls freebusy.query on `primary` and generates candidate slots from config
  - Returns up to 5 slots, each with `start_iso` and a spoken label in the caller's timezone
- `confirm_email(raw: str) -> dict`
  - Normalizes common speech artifacts ("at" to "@", "dot" to ".", removes spaces)
  - Validates syntax and that the domain has an MX record
  - Returns `{status: "valid" | "needs_confirmation" | "invalid", email, spelled}` where `spelled` is the address with letters separated by spaces for readback
- `book_meeting(start_iso: str, caller_timezone: str, name: str, company: str, role: str, email: str, reason: str)`
  - Re-checks freebusy right before booking (race condition)
  - Calls events.insert with:
    - summary "Intro: {name} ({company})"
    - description holding reason, role, caller phone and a call summary
    - attendees [caller email]
    - `conferenceData.createRequest` for a Meet link, with `conferenceDataVersion=1`
    - `sendUpdates="all"`
  - Returns the event time and Meet link
- `log_request(name, company, reason, preferred_times, phone)`
  - Appends to `traces/requests.jsonl` for manual follow-up
- `end_call()`
  - Waits for the agent's current audio to finish, then calls `ctx.delete_room()`

## Availability config (env)
- `OWNER_TZ=America/New_York`
- `BOOKABLE_DAYS=Mon-Fri`
- `BOOKABLE_HOURS=10-18`
- `MEETING_MINUTES=30`
- `BUFFER_MINUTES=15`
- `MAX_PER_DAY=4`
- `MIN_NOTICE_HOURS=12`
- `HORIZON_DAYS=14`
- `MODE=live` (or `realtime` for the turn-based fallback)

## Abuse limits
- Max call length is 8 minutes; end the call gracefully when it's reached.
- One booking per caller number per 7 days, checked against the trace files.
- Block numbers listed in a `BLOCKLIST` env var.

## Trace schema (per call)
- room, caller_phone, start/end time, mode (live or realtime)
- Voice model id and backend model id as reported by the session
- Full chat history including tool calls and results
- Per-turn latency metrics
- outcome: booked | logged_request | abandoned | blocked | error
- event_id if one was booked

## Setup (README)
1. Create a LiveKit Cloud project and set `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`.
2. Set `OPENAI_API_KEY` on a paid tier (GPT-Live is not on the Free tier).
3. In Google Cloud:
   - Enable the Calendar API.
   - Create an OAuth Desktop client and download `credentials.json`.
   - Run `python auth_google.py` to produce `token.json`.
4. Run `python agent.py console` to test locally, then `python agent.py dev`.
5. In LiveKit Cloud:
   - Buy a phone number.
   - Create an inbound dispatch rule that routes to agent `intake`.
6. Deploy with `lk agent create` (LiveKit Cloud agents) or on any VM running `python agent.py start`.

## Acceptance tests
- Console call books a real event, the caller email gets an invite, and the event includes a Meet link.
- A busy slot is never offered, and booking re-checks availability.
- A misheard email leads to `confirm_email` returning `needs_confirmation`, a readback, a retry, then `log_request` after two failures.
- A request outside bookable hours gets alternative slots offered.
- Interrupting the agent mid-sentence on a phone call stops its audio within one second.
- A trace JSON is written for every call, including abandoned and blocked ones, and records both model ids.
- `MODE=realtime` works with no code changes beyond the env var.

## Out of scope for v1
- SMS or email confirmation beyond the calendar invite
- Rescheduling or cancellation by phone
- Postgres
- Dashboard
- `delegation="client"` mode (we would lose function tools)
- OpenAI provider tools such as WebSearch
