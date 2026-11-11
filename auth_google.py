"""One-time OAuth flow for the owner's Google account.

Usage:
    python auth_google.py

Reads credentials.json (an OAuth "Desktop app" client from Google Cloud) and writes
token.json. Re-run if the token is revoked. Paths come from GOOGLE_CREDENTIALS_PATH and
GOOGLE_TOKEN_PATH when set.
"""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import Settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def load_credentials(settings: Settings, interactive: bool = False) -> Credentials:
    """Load the owner's OAuth token.

    Order: GOOGLE_TOKEN_JSON env var (the contents of token.json, for hosted deployments
    where files are awkward), then token_path on disk. Refreshes when expired.
    """
    creds: Credentials | None = None
    token_env = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_env:
        creds = Credentials.from_authorized_user_info(json.loads(token_env), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds
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


def manual_flow(settings: Settings, code: str | None) -> Credentials:
    """Headless variant: print the consent URL, then exchange a pasted code.

    The Desktop client type accepts any http://localhost redirect, so the browser will fail
    to load the redirect page. Copy the `code` query parameter from that URL.
    """
    # No PKCE: the URL is printed in one process and the code exchanged in another, so a
    # per-process code verifier would be lost. Desktop clients authenticate with the secret.
    flow = InstalledAppFlow.from_client_secrets_file(
        str(settings.credentials_path),
        SCOPES,
        redirect_uri="http://localhost:1",
        autogenerate_code_verifier=False,
    )
    if not code:
        url, _ = flow.authorization_url(access_type="offline", prompt="consent")
        print("Open this URL, approve, then re-run with --code <code from the redirect URL>:\n")
        print(url)
        raise SystemExit(2)
    flow.fetch_token(code=code.strip())
    creds = flow.credentials
    settings.token_path.write_text(creds.to_json())
    return creds


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual", action="store_true", help="print a URL instead of opening a browser")
    parser.add_argument("--code", help="authorization code from the redirect URL (with --manual)")
    args = parser.parse_args()

    load_dotenv()
    settings = Settings.from_env()
    if args.manual or args.code:
        creds = manual_flow(settings, args.code)
    else:
        creds = load_credentials(settings, interactive=True)
    print(f"Wrote {settings.token_path}. Scopes: {', '.join(creds.scopes or SCOPES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
