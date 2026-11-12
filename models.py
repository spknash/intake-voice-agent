"""Builds the voice model for the configured MODE.

live     -> GPT-Live-1 (full-duplex) delegating reasoning to its default backend model.
realtime -> gpt-realtime-2.1 (turn-based) as a fallback with identical tools.
"""

from __future__ import annotations

from livekit.agents import llm
from livekit.plugins import openai

from config import Settings

DEFAULT_VOICE = "marin"
REALTIME_FALLBACK_MODEL = "gpt-realtime-2.1"


def _live_voice(settings: Settings) -> str | dict[str, str]:
    # Custom prompt-designed or cloned voices are referenced by id; built-ins by name.
    if settings.voice.startswith("voice_"):
        return {"id": settings.voice}
    return settings.voice or DEFAULT_VOICE


def build(settings: Settings, backend_instructions: str) -> llm.DuplexModel | llm.RealtimeModel:
    if settings.mode == "live":
        return openai.realtime.GPTLiveModel(
            voice=_live_voice(settings),
            # delegation="responses" is the default: a backend Responses model does the
            # reasoning and tool calling, our @function_tool methods run in-process.
            # We leave responses_options["model"] unset so OpenAI's default backend applies.
            responses_options={
                "instructions": backend_instructions,
                # low keeps the backend's turn latency down; the flow is simple
                "reasoning": {"effort": "low"},
                "text": {"verbosity": "low"},
            },
            # Recycle the websocket well before the 8-minute call cap would otherwise
            # collide with any provider-side session limit.
            max_session_duration=20 * 60,
        )

    # Custom voices only work on GPT-Live; the realtime fallback uses a built-in name.
    voice = settings.voice if not settings.voice.startswith("voice_") else DEFAULT_VOICE
    return openai.realtime.RealtimeModel(model=REALTIME_FALLBACK_MODEL, voice=voice)


def describe(settings: Settings) -> dict[str, str | None]:
    """Model identifiers recorded in each trace."""
    if settings.mode == "live":
        return {
            "mode": "live",
            "voice_model": openai.realtime.GPTLiveModel.__init__.__kwdefaults__["model"],
            "backend_model": "openai-default",
            "voice": settings.voice,
        }
    return {"mode": "realtime", "voice_model": REALTIME_FALLBACK_MODEL, "backend_model": None, "voice": settings.voice}
