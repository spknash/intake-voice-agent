"""Create a test room, dispatch the `intake` agent into it, and print a browser join link.

Usage:
    python scripts/test_call.py [room-name]

Requires LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET in the environment or .env, and a
running worker (`python agent.py dev`). Open the printed link, allow the microphone, and talk.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import timedelta
from urllib.parse import quote

from dotenv import load_dotenv
from livekit import api

AGENT_NAME = "intake"


async def main(room: str) -> None:
    url = os.environ["LIVEKIT_URL"]
    lk = api.LiveKitAPI(url.replace("wss://", "https://"))
    try:
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=room)
        )
    finally:
        await lk.aclose()

    token = (
        api.AccessToken()
        .with_identity("tester")
        .with_name("Tester")
        .with_ttl(timedelta(hours=1))
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
    print(f"Room: {room}")
    print("Open in a browser (allow mic):")
    print(f"https://meet.livekit.io/custom?liveKitUrl={quote(url, safe='')}&token={token}")


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else f"test-{int(time.time())}"))
