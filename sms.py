"""Outbound SMS through Twilio's REST API, used for booking confirmations in phone mode.

Authenticates with an API key (SID + secret) rather than the account auth token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from config import Settings

API = "https://api.twilio.com/2010-04-01"


class SmsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Confirmation:
    owner_name: str
    when: str  # already spoken-style, e.g. "Friday November 13 at 3:00 PM Eastern"
    meet_link: str | None
    manage_link: str | None

    def text(self) -> str:
        lines = [f"Booked: {self.when} with {self.owner_name}."]
        if self.meet_link:
            lines.append(f"Join: {self.meet_link}")
        if self.manage_link:
            lines.append(f"Change or cancel: {self.manage_link}")
        lines.append("Reply STOP to opt out.")
        return "\n".join(lines)


class Twilio:
    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(
            self.s.twilio_account_sid
            and self.s.twilio_api_key_sid
            and self.s.twilio_api_key_secret
            and self.s.sms_from
        )

    async def send(self, to: str, body: str) -> dict[str, Any]:
        if not self.enabled:
            raise SmsError("SMS is not configured")
        url = f"{API}/Accounts/{self.s.twilio_account_sid}/Messages.json"
        auth = aiohttp.BasicAuth(self.s.twilio_api_key_sid, self.s.twilio_api_key_secret)
        data = {"To": to, "From": self.s.sms_from, "Body": body}
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.post(url, data=data, auth=auth) as r:
                payload = await r.json()
                if r.status >= 400:
                    raise SmsError(f"Twilio {r.status} {payload.get('code')}: {payload.get('message')}")
                return payload
