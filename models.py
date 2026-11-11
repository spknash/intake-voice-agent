"""Builds the voice model for the configured MODE.

live     -> GPT-Live-1 (full-duplex) delegating reasoning to its default backend model.
realtime -> gpt-realtime-2.1 (turn-based) as a fallback with identical tools.
"""

from __future__ import annotations

from livekit.agents import llm
from livekit.plugins import openai

from config import Settings

VOICE = "marin"
REALTIME_FALLBACK_MODEL = "gpt-realtime-2.1"


def build(settings: Settings, backend_instructions: str) -> llm.DuplexModel | llm.RealtimeModel:
    if settings.mode == "live":
        return openai.realtime.GPTLiveModel(
            voice=VOICE,
            # delegation="responses" is the default: a backend Responses model does the
            # reasoning and tool calling, our @function_tool methods run in-process.
            # We leave responses_options["model"] unset so OpenAI's default backend applies.
            responses_options={
                "instructions": backend_instructions,
                "reasoning": {"effort": "medium"},
                "text": {"verbosity": "low"},
            },
            # Recycle the websocket well before the 8-minute call cap would otherwise
            # collide with any provider-side session limit.
            max_session_duration=20 * 60,
        )

    return openai.realtime.RealtimeModel(
        model=REALTIME_FALLBACK_MODEL,
        voice=VOICE,
    )


def describe(settings: Settings) -> dict[str, str | None]:
    """Model identifiers recorded in each trace."""
    if settings.mode == "live":
        return {
            "mode": "live",
            "voice_model": openai.realtime.GPTLiveModel.__init__.__kwdefaults__["model"],
            "backend_model": "openai-default",
        }
    return {"mode": "realtime", "voice_model": REALTIME_FALLBACK_MODEL, "backend_model": None}
