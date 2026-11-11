# Intake voice agent

A phone number anyone can call to book a 30-minute intro meeting with Suhaas. A voice agent
learns who is calling and why, offers open times from Google Calendar, confirms an email, books
the event with a Meet link, and sends the invite. Every call is written to `traces/` as JSON.

See [PLAN.md](PLAN.md) for the design.

## Architecture

| Layer | Model | Job |
|---|---|---|
| Voice | OpenAI GPT-Live-1 (full-duplex) | Listening, speaking, barge-in, pacing |
| Reasoning | GPT-Live's default backend Responses model | Intake flow, tool calls, validation |

GPT-Live runs in `responses` delegation mode. The five tools in `agent.py` run in this process.
`MODE=realtime` swaps in turn-based `gpt-realtime-2.1` with the same tools.

## Files

- `agent.py` entrypoint, `IntakeAgent` with tools, abuse limits, trace writer
- `models.py` builds the voice model for `MODE`
- `prompts.py` voice-layer and backend-layer instructions
- `gcal.py` free/busy, slot generation, event creation
- `emailcheck.py` speech-to-email normalization and validation
- `traces.py` per-call trace files, request log, 7-day cooldown lookup
- `auth_google.py` one-time OAuth flow that writes `token.json`
- `config.py` settings from env

## Setup

1. Python 3.11+.
   ```bash
   python -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```
2. LiveKit Cloud: create a project, copy `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` into `.env`.
3. OpenAI: set `OPENAI_API_KEY` from a paid-tier org. GPT-Live is not on the Free tier.
4. Google Cloud:
   - Enable the Google Calendar API.
   - Create an OAuth client, type **Desktop app**, download it as `credentials.json` in this folder.
   - If the OAuth consent screen is in Testing, add Suhaas's Gmail as a test user.
   - Run the one-time auth flow, which opens a browser and writes `token.json`:
     ```bash
     python auth_google.py
     ```
5. Test locally with your microphone:
   ```bash
   python agent.py console
   ```
   Then run as a dev worker connected to LiveKit Cloud:
   ```bash
   python agent.py dev
   ```
   With the worker running, talk to it from a browser without a phone number:
   ```bash
   python scripts/test_call.py
   ```
   It dispatches the agent into a room and prints a LiveKit Meet link.
6. LiveKit Cloud telephony:
   - Buy a phone number.
   - Create an inbound dispatch rule that dispatches agent name `intake`.
   - Call the number.
7. Deploy. Either run `python agent.py start` on any always-on machine, or use LiveKit Cloud
   agents with the included `Dockerfile`:
   ```bash
   lk agent create --secrets-file .env
   ```
   Hosted deployments have no `token.json` on disk, so put the token contents in an env var
   before running that command:
   ```bash
   echo "GOOGLE_TOKEN_JSON=$(cat token.json | tr -d '\n')" >> .env
   ```
   `GOOGLE_TOKEN_JSON` takes precedence over `GOOGLE_TOKEN_PATH` when set.

## Configuration

All in `.env`. Defaults in parentheses.

- `MODE` live | realtime (live)
- `OWNER_NAME` (Suhaas), `OWNER_TZ` (America/New_York)
- `BOOKABLE_DAYS` (Mon-Fri), `BOOKABLE_HOURS` (10-18), `MEETING_MINUTES` (30), `BUFFER_MINUTES` (15)
- `MAX_PER_DAY` (4), `MIN_NOTICE_HOURS` (12), `HORIZON_DAYS` (14)
- `MAX_CALL_SECONDS` (480), `BOOKING_COOLDOWN_DAYS` (7), `BLOCKLIST` (comma-separated E.164 numbers)
- `GOOGLE_CALENDAR_ID` (primary), `GOOGLE_CREDENTIALS_PATH`, `GOOGLE_TOKEN_PATH`, `GOOGLE_TOKEN_JSON`, `TRACES_DIR`

### Headless Google auth

On a machine without a browser, print the consent URL, approve it elsewhere, then exchange the
code from the failed `localhost` redirect:

```bash
python auth_google.py --manual
```

```bash
python auth_google.py --code '<code from redirect URL>'
```

## Traces

One file per call in `traces/`: room, caller phone, start and end time, mode, voice and backend
model ids, outcome (`booked`, `logged_request`, `abandoned`, `blocked`, `error`), event id and Meet
link, a tool log, and LiveKit's full session report with chat history and metrics.
Requests that could not be booked append to `traces/requests.jsonl`.

## Tests

```bash
python -m pytest -q
```

Covers slot generation, buffers, max-per-day, minimum notice, caller timezone windows, email
normalization, config parsing, and the booking cooldown.

## Known limits

- GPT-Live cannot speak a fixed script verbatim. The greeting and email readback are best-effort;
  email correctness lives in the `confirm_email` tool and the explicit yes it asks for.
- Voice and instructions cannot change mid-session.
- `session.say()` is never used because GPT-Live has no TTS attached.
- Billing: $0.05 per minute of voice plus normal token pricing for the backend model.
