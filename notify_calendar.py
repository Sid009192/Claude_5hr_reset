"""Google Calendar delivery module for the 5-hour-window notifier.

This is the Calendar side of the notification layer, the sibling of
``notify_telegram.py``. For a given day it pushes one event per usage window --
the *golden heavy-work slot* (the longest-lead window before the quota resets,
golden -> reset) -- into your Google Calendar so the plan lives next to the rest
of your day.

Design constraints (mirroring the Telegram module):
  * ``sync_day()`` must NEVER raise. A notifier that crashes the scheduler task
    is worse than one that quietly returns 0. Every failure path prints a clear
    reason and returns a count (0 on failure).
  * Idempotent. Each event gets a deterministic id derived from the window's
    open time, so re-running a day UPDATES the existing events instead of
    creating duplicates. Safe to run from both the midnight publish AND by hand.

Auth: OAuth 2.0 "Desktop app" flow. The client id/secret live in the gitignored
``.env`` as ``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET``. The first run opens
a browser for one-time consent and caches a refresh token in ``token.json``
(also gitignored); every run after that is silent and headless.

Usage:
    uv run python notify_calendar.py                 # push TODAY's windows
    uv run python notify_calendar.py --day tomorrow  # push TOMORROW's windows
    uv run python notify_calendar.py --day 2026-06-28
    uv run python notify_calendar.py --auth          # just do the consent / token
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import reset_schedule as rs

# Emoji in event summaries; keep a cp1252 console from choking on prints.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"
TOKEN_PATH = HERE / "token.json"

# Narrowest scope that lets us create/update events (not read your whole life).
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# Defaults if the [calendar] config block is absent.
DEFAULT_CALENDAR_ID = "primary"
DEFAULT_TIMEZONE = "Asia/Kolkata"

# Rotating event colours (Google colorId), cycled per window so a day's events
# alternate instead of being one flat block. Leads with the user's favourites.
COLOR_CYCLE = [
    "10",  # Basil    (green)
    "3",   # Grape    (purple)
    "5",   # Banana   (yellow)
    "9",   # Blueberry(blue)
    "6",   # Tangerine(orange)
]


# --------------------------------------------------------------------------- #
# .env reader (stdlib; same minimal parser shape as notify_telegram)
# --------------------------------------------------------------------------- #

def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"[calendar] Could not read {path}: {exc}")
    return values


def _load_oauth_client() -> tuple[str, str]:
    """(client_id, client_secret) from env, falling back to .env. Empty if unset."""
    file_vals = _read_env_file(ENV_PATH)
    cid = (os.environ.get("GOOGLE_CLIENT_ID")
           or file_vals.get("GOOGLE_CLIENT_ID", "")).strip()
    secret = (os.environ.get("GOOGLE_CLIENT_SECRET")
              or file_vals.get("GOOGLE_CLIENT_SECRET", "")).strip()
    return cid, secret


# --------------------------------------------------------------------------- #
# Auth / service
# --------------------------------------------------------------------------- #

def _get_service():
    """Build an authorized Calendar service, or return None with a printed reason.

    Reuses token.json when possible, refreshes it silently when expired, and only
    falls back to the interactive browser consent on first run / revoked token.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        print(f"[calendar] Google libraries missing ({exc}). Run: "
              "uv add google-auth google-auth-oauthlib google-api-python-client")
        return None

    creds = None
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception as exc:  # corrupt token -> fall through to re-consent
            print(f"[calendar] Ignoring unreadable token.json ({exc}).")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                print(f"[calendar] Token refresh failed ({exc}); re-consenting.")
                creds = None
        if not creds:
            cid, secret = _load_oauth_client()
            if not cid or not secret:
                print("[calendar] OAuth client missing. Set GOOGLE_CLIENT_ID and "
                      "GOOGLE_CLIENT_SECRET in .env (copy .env.example), then re-run.")
                return None
            client_config = {
                "installed": {
                    "client_id": cid,
                    "client_secret": secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
            try:
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as exc:
                print(f"[calendar] Consent flow failed: {exc}")
                return None
        try:
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        except OSError as exc:
            print(f"[calendar] Could not cache token ({exc}); will re-consent next time.")

    try:
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:
        print(f"[calendar] Could not build Calendar service: {exc}")
        return None


# --------------------------------------------------------------------------- #
# Event shaping
# --------------------------------------------------------------------------- #

def _event_id(open_dt: datetime) -> str:
    """Deterministic, collision-free event id for a window's open time.

    Calendar ids allow only [a-v0-9]; lowercase hex (0-9a-f) is a safe subset,
    and the prefix 'claude' uses only a-v letters. Same window -> same id, which
    is what makes re-runs update rather than duplicate.
    """
    return "claude" + format(int(open_dt.timestamp()), "x")


def _build_event(w: rs.Window, cfg: rs.Config, tz: str, idx: int = 0) -> dict:
    lead = max(cfg.lead_minutes)            # golden slot = longest lead
    golden = w.reset - timedelta(minutes=lead)
    o = w.open.strftime("%I:%M %p").lstrip("0")
    r = w.reset.strftime("%I:%M %p").lstrip("0")
    return {
        "id": _event_id(w.open),
        "summary": "Claude golden window",
        "description": (
            f"Golden heavy-work slot before the Claude quota resets at {r}.\n"
            f"Window opened {o}; reset {r}.\n\n"
            "Auto-managed by the 5-hour-window notifier."
        ),
        "start": {"dateTime": golden.replace(microsecond=0).isoformat(), "timeZone": tz},
        "end": {"dateTime": w.reset.replace(microsecond=0).isoformat(), "timeZone": tz},
        "colorId": COLOR_CYCLE[idx % len(COLOR_CYCLE)],
        "reminders": {"useDefault": False},
        "transparency": "transparent",       # doesn't block you as "busy"
    }


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def sync_day(day: date, cfg: rs.Config | None = None,
             anchor: datetime | None = None) -> int:
    """Upsert calendar events for every window opening on ``day``.

    Returns the number of events created/updated. Never raises: any failure
    prints a reason and returns 0 (or a partial count).
    """
    cfg = cfg or rs.load_config()
    if anchor is None:
        anchor = rs.load_anchor(cfg)

    cal_cfg = cfg.raw.get("calendar", {})
    calendar_id = cal_cfg.get("calendar_id", DEFAULT_CALENDAR_ID)
    tz = cal_cfg.get("timezone", DEFAULT_TIMEZONE)

    wins = rs.windows_for_day(day, cfg, anchor)
    if not wins:
        print(f"[calendar] No windows for {day:%a %d %b}; nothing to sync.")
        return 0

    service = _get_service()
    if service is None:
        return 0

    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        HttpError = Exception  # type: ignore

    count = 0
    for idx, w in enumerate(wins):
        event = _build_event(w, cfg, tz, idx)
        try:
            service.events().insert(calendarId=calendar_id, body=event).execute()
            count += 1
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status == 409:
                # Event id already exists -> update so edited times propagate.
                try:
                    service.events().update(
                        calendarId=calendar_id, eventId=event["id"], body=event
                    ).execute()
                    count += 1
                except Exception as exc2:
                    print(f"[calendar] update failed for {event['id']}: {exc2}")
            else:
                print(f"[calendar] insert failed for {event['id']}: {exc}")
        except Exception as exc:  # noqa: BLE001 -- never raise.
            print(f"[calendar] unexpected error for {event['id']}: {exc}")

    print(f"[calendar] synced {count}/{len(wins)} window(s) for {day:%a %d %b}.")
    return count


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_day(s: str) -> date:
    if s == "today":
        return date.today()
    if s == "tomorrow":
        return date.today() + timedelta(days=1)
    return date.fromisoformat(s)  # e.g. 2026-06-28


def main() -> None:
    ap = argparse.ArgumentParser(description="Push Claude heavy-work windows to Google Calendar.")
    ap.add_argument("--day", default="today",
                    help="today | tomorrow | YYYY-MM-DD (default: today).")
    ap.add_argument("--auth", action="store_true",
                    help="Run the one-time consent / refresh the token and exit.")
    args = ap.parse_args()

    if args.auth:
        service = _get_service()
        print("[calendar] auth OK; token.json is ready." if service
              else "[calendar] auth did NOT complete (see reason above).")
        return

    sync_day(_parse_day(args.day))


if __name__ == "__main__":
    main()
