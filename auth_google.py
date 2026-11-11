"""One-time OAuth flow for the owner's Google account.

Usage:
    python auth_google.py

Reads credentials.json (an OAuth "Desktop app" client from Google Cloud) and writes
token.json. Re-run if the token is revoked. Paths come from GOOGLE_CREDENTIALS_PATH and
GOOGLE_TOKEN_PATH when set.
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import Settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def load_credentials(settings: Settings, interactive: bool = False) -> Credentials:
    creds: Credentials | None = None
    if settings.token_path.exists():
        creds = Credentials.from_authorized_user_file(str(settings.token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        settings.token_path.write_text(creds.to_json())
        return creds
    if not interactive:
        raise RuntimeError(
            f"No valid Google token at {settings.token_path}. Run `python auth_google.py` first."
        )
    if not settings.credentials_path.exists():
        raise FileNotFoundError(
            f"{settings.credentials_path} not found. Download an OAuth Desktop client JSON "
            "from Google Cloud Console and save it there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(settings.credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    settings.token_path.write_text(creds.to_json())
    return creds


def main() -> int:
    load_dotenv()
    settings = Settings.from_env()
    creds = load_credentials(settings, interactive=True)
    print(f"Wrote {settings.token_path}. Scopes: {', '.join(creds.scopes or SCOPES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
