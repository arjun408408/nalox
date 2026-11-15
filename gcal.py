"""Google Calendar for Nalox (v4.3) — "what's on my calendar today?"

Reuses the SAME Google Cloud project + client secret as the YouTube
reply-all (youtube_client_secret.json in the install folder — see
the Calendar section appended to SETUP-YOUTUBE.txt). The only
difference: a read-only scope and its own cached token file
(gcal_token.json), so the one-time browser consent happens once for
Calendar, independently of YouTube.

Everything is failure-guarded: a missing setup, a declined consent
or a network error returns a calm status, never an exception.
"""
import logging
import os
from datetime import datetime, time as dtime, timedelta

log = logging.getLogger("nalox.gcal")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_PATH = os.path.join(BASE_DIR, "youtube_client_secret.json")
TOKEN_PATH = os.path.join(BASE_DIR, "gcal_token.json")
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def is_setup():
    """True once the shared Google client secret is in the folder."""
    return os.path.exists(SECRET_PATH)


def get_service():
    """Build an authenticated Calendar v3 service.

    Returns (service, "ok") / (None, "not_setup") / (None, "error: ...").
    Mirrors youtube_tools.get_service: cached token, refresh when
    possible, browser consent (InstalledAppFlow) the first time.
    """
    if not os.path.exists(SECRET_PATH):
        return None, "not_setup"
    try:
        from googleapiclient.discovery import build

        creds = None
        if os.path.exists(TOKEN_PATH):
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file(
                TOKEN_PATH, SCOPES)
        if creds is None or not creds.valid:
            if creds is not None and creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
            else:
                from google_auth_oauthlib.flow import InstalledAppFlow
                flow = InstalledAppFlow.from_client_secrets_file(
                    SECRET_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        return build("calendar", "v3", credentials=creds), "ok"
    except Exception as exc:
        return None, f"error: {exc}"


def _fmt_start(start):
    """'2026-11-15T14:30:00+05:30' -> '2:30 PM'; a date -> 'All day'."""
    raw = (start or {}).get("dateTime") or ""
    if raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            return raw[11:16] or "All day"
    return "All day"


def today_events():
    """Today's events on the primary calendar: [{start, title}].

    Returns None when Calendar is not set up / not reachable, so the
    caller can give the setup line instead of a wrong "nothing".
    """
    service, status = get_service()
    if service is None:
        log.info("Calendar unavailable: %s", status)
        return None
    try:
        now = datetime.now().astimezone()
        start = datetime.combine(now.date(), dtime.min,
                                 tzinfo=now.tzinfo)
        end = start + timedelta(days=1)
        resp = service.events().list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=20,
        ).execute()
        events = []
        for item in resp.get("items") or []:
            title = (item.get("summary") or "(no title)").strip()
            events.append({"start": _fmt_start(item.get("start") or {}),
                           "title": title})
        return events
    except Exception as exc:
        log.warning("Calendar fetch failed: %s", exc)
        return None
