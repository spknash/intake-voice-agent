"""Normalize and validate an email address transcribed from speech."""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass

import dns.resolver

_SPOKEN = [
    (r"\s+at\s+sign\s+", "@"),
    (r"\s+at\s+", "@"),
    (r"\s+dot\s+", "."),
    (r"\s+period\s+", "."),
    (r"\s+underscore\s+", "_"),
    (r"\s+under\s+score\s+", "_"),
    (r"\s+dash\s+", "-"),
    (r"\s+hyphen\s+", "-"),
    (r"\s+minus\s+", "-"),
    (r"\s+plus\s+", "+"),
]
_TRAILING = [
    (r"\s*\bdot\s+com\b", ".com"),
    (r"\s*\bdot\s+org\b", ".org"),
    (r"\s*\bdot\s+net\b", ".net"),
    (r"\s*\bdot\s+io\b", ".io"),
    (r"\s*\bdot\s+ai\b", ".ai"),
    (r"\s*\bdot\s+co\b", ".co"),
    (r"\s*\bdot\s+edu\b", ".edu"),
]
_SYNTAX = re.compile(r"^[a-z0-9][a-z0-9._%+-]*@[a-z0-9.-]+\.[a-z]{2,}$")
_COMMON_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "protonmail.com",
    "proton.me",
    "me.com",
    "live.com",
}


@dataclass
class EmailCheck:
    status: str  # valid | needs_confirmation | invalid
    email: str
    spelled: str
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


def normalize(raw: str) -> tuple[str, bool]:
    """Return (normalized, changed) where changed means spoken tokens were rewritten."""
    s = " " + raw.strip().lower() + " "
    original = s
    for pat, rep in _TRAILING:
        s = re.sub(pat, rep, s)
    for pat, rep in _SPOKEN:
        s = re.sub(pat, rep, s)
    s = s.strip().replace(" ", "")
    s = s.rstrip(".")
    return s, s != original.strip().replace(" ", "")


def spell(email: str) -> str:
    """'a.b@x.com' -> 'a dot b at x dot com' with letters separated for clear readback."""
    words = []
    for ch in email:
        if ch == "@":
            words.append("at")
        elif ch == ".":
            words.append("dot")
        elif ch == "_":
            words.append("underscore")
        elif ch == "-":
            words.append("dash")
        elif ch == "+":
            words.append("plus")
        elif ch.isdigit():
            words.append(ch)
        else:
            words.append(ch.upper())
    return " ".join(words)


def _has_mx(domain: str) -> bool | None:
    """True/False when DNS answers, None when DNS is unreachable or times out."""
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 2.0
        resolver.timeout = 1.0
        try:
            answers = resolver.resolve(domain, "MX")
            return len(answers) > 0
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            try:
                resolver.resolve(domain, "A")
                return True
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                return False
    except Exception:
        return None


async def check_email(raw: str) -> EmailCheck:
    email, changed = normalize(raw)
    spelled = spell(email)
    if not _SYNTAX.match(email):
        return EmailCheck(
            "invalid", email, spelled, "Not a valid address. Ask the caller to spell it."
        )
    domain = email.rsplit("@", 1)[1]
    if domain in _COMMON_DOMAINS:
        mx = True
    else:
        mx = await asyncio.to_thread(_has_mx, domain)
    if mx is False:
        return EmailCheck(
            "needs_confirmation",
            email,
            spelled,
            "The domain does not appear to receive mail. Read it back letter by letter.",
        )
    if mx is None or changed:
        return EmailCheck(
            "needs_confirmation",
            email,
            spelled,
            "Plausible, but was transcribed from speech. Read it back letter by letter.",
        )
    return EmailCheck("valid", email, spelled, "Looks valid. Read it back once to confirm.")
