"""
Claude auto-sender
==================
Sends a message to claude.ai on a fixed schedule using a DEDICATED, separate
Playwright-controlled browser session. It never touches your real mouse or
keyboard, so you can keep using your laptop normally while it runs.

Usage
-----
1. One-time login (opens a visible window so you can sign in once):
       uv run python autosend.py --login

2. Sends are driven one-shot by Windows Task Scheduler:
       uv run python autosend.py --once
"""

import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import reset_schedule as rs  # shared schedule core (window length, last_reset path)

# --------------------------------------------------------------------------- #
# CONFIG  --  edit these to taste
# --------------------------------------------------------------------------- #

# The message that gets sent each time.
MESSAGE = "hi"

# Hide the browser for --once?
# claude.ai blocks true headless, so True does NOT use headless -- instead it
# runs a REAL window parked off-screen (invisible to you, accepted by claude.ai).
# Set to False only if you want to watch the window on-screen.
HEADLESS = True

# Where the logged-in browser session is stored (so you log in only once).
PROFILE_DIR = Path(__file__).parent / "pw-profile"

# Remembers the single conversation we reuse, so we don't clutter chat history
# with a new chat every time. Deleted/invalid chats are recreated automatically.
CONVERSATION_FILE = Path(__file__).parent / "conversation_url.txt"

# Ground-truth anchor for the notification system. Written after each scheduled
# send by reading the REAL reset off claude.ai's usage page (and by --autosync),
# so reset_schedule.py never drifts. Read by the toast/telegram/digest scripts.
LAST_RESET_FILE = Path(__file__).parent / "last_reset.txt"

# The re-arm "brain": after each send we re-pin the next send + ping triggers to
# the freshly-updated anchor (Option A self-rescheduling). See schedule_rearm.ps1.
REARM_SCRIPT = Path(__file__).parent / "schedule_rearm.ps1"

# claude.ai URLs
NEW_CHAT_URL = "https://claude.ai/new"

# Selector for the chat input box (ProseMirror contenteditable).
EDITOR_SELECTOR = 'div[contenteditable="true"]'

# --------------------------------------------------------------------------- #

LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def open_context(p, hidden: bool):
    """Open the persistent (logged-in) browser context.

    claude.ai blocks ALL headless modes (old shell and new-headless alike), but
    accepts a normal headed browser. So 'hidden' does NOT mean headless here:

    hidden=True  -> a real headed window parked far off-screen (you never see it,
                    but claude.ai sees a genuine browser and lets it through).
    hidden=False -> a normal on-screen window (used by --test / --login).
    """
    args = list(LAUNCH_ARGS)
    if hidden:
        args += ["--window-position=-32000,-32000", "--window-size=1280,900"]
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        args=args,
        viewport={"width": 1280, "height": 900},
    )


def do_login() -> None:
    """Open a visible browser so the user can log in once. Session is saved."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=LAUNCH_ARGS,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://claude.ai", wait_until="domcontentloaded")
        log("A browser window opened. Log in to Claude there.")
        input(">>> After you are fully logged in, press Enter here to save the session... ")
        try:
            ctx.close()
        except Exception:
            # Closing can emit harmless 'Target closed' noise — the session
            # cookies are already saved to the profile on disk by this point.
            pass
    log("Session saved. Verify it with:  uv run python autosend.py --test")


def _read_saved_conversation() -> str | None:
    if CONVERSATION_FILE.exists():
        url = CONVERSATION_FILE.read_text(encoding="utf-8").strip()
        if url.startswith("http"):
            return url
    return None


def _open_chat(page) -> bool:
    """Navigate to the reused conversation if we have one and it still loads;
    otherwise open a fresh chat. Returns True if this is a brand-new chat (so the
    caller knows to save its URL after sending)."""
    saved = _read_saved_conversation()
    if saved:
        page.goto(saved, wait_until="domcontentloaded")
        try:
            page.locator(EDITOR_SELECTOR).first.wait_for(state="visible", timeout=20_000)
            return False  # reused the existing conversation
        except PWTimeout:
            log("Saved chat didn't load (maybe deleted). Creating a new one.")
    # No saved chat, or it failed to load -> start fresh.
    page.goto(NEW_CHAT_URL, wait_until="domcontentloaded")
    page.locator(EDITOR_SELECTOR).first.wait_for(state="visible", timeout=60_000)
    return True


def send_message(page) -> None:
    """Send MESSAGE into the single reused chat (creating it the first time)."""
    is_new_chat = _open_chat(page)

    editor = page.locator(EDITOR_SELECTOR).first
    editor.click()
    page.keyboard.insert_text(MESSAGE)
    # Small settle so the UI registers the text before we submit.
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")
    log(f"Sent message: {MESSAGE!r}")
    # Give the request a moment to actually fire before we move on. The anchor is
    # written separately by _anchor_after_send() using the usage page (ground
    # truth), NOT a naive 'now' -- a send can land mid-window and not reset.
    page.wait_for_timeout(3_000)

    # If this was a new chat, claude.ai navigates to /chat/<id>. Remember it so
    # every future send reuses this same conversation (no history clutter).
    if is_new_chat and "/chat/" in page.url:
        CONVERSATION_FILE.write_text(page.url, encoding="utf-8")
        log(f"Saved conversation for reuse: {page.url}")


def run_test() -> None:
    """Send exactly one message right now, then exit. Used to verify the saved
    session and the whole send pipeline without waiting for the schedule.
    Runs visibly so you can watch it work."""
    if not PROFILE_DIR.exists():
        log("No saved session found. Run first:  uv run python autosend.py --login")
        sys.exit(1)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,  # visible so you can confirm the message lands
            args=LAUNCH_ARGS,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            send_message(page)
            log("Test send complete. Check your claude.ai for the message.")
            page.wait_for_timeout(4_000)
        except PWTimeout:
            log("Could not find the chat box — you may not be logged in.")
            log("Fix: run  uv run python autosend.py --login")
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def run_once() -> None:
    """Send exactly one message headless, then exit. This is what Windows Task
    Scheduler calls on each trigger."""
    if not PROFILE_DIR.exists():
        log("No saved session found. Run first:  uv run python autosend.py --login")
        sys.exit(1)

    with sync_playwright() as p:
        ctx = open_context(p, hidden=HEADLESS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        exit_code = 0
        try:
            _smart_sync(page)          # scrape usage, send only if it opens a window
            _rearm()                   # re-pin next send + pings to the new anchor
        except PWTimeout:
            log("Could not find the chat box — you may be logged out, or claude.ai "
                "blocked headless mode. Try  --login  and/or set HEADLESS = False.")
            exit_code = 1
        except Exception as e:
            log(f"Send failed: {e!r}")
            exit_code = 1
        finally:
            try:
                ctx.close()
            except Exception:
                pass
        sys.exit(exit_code)


# --------------------------------------------------------------------------- #
# --autosync : re-anchor last_reset.txt to the REAL window
# --------------------------------------------------------------------------- #

def _parse_reset_clock(s: str, now: datetime | None = None) -> datetime | None:
    """Parse a clock time like '12:39 AM' or '23:50' into the NEXT future
    datetime with that time (reset times are always ahead of now)."""
    now = now or datetime.now()
    m = re.search(r"(\d{1,2}):(\d{2})\s*([AaPp][Mm])", s)
    if m:
        hh = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
        mm = int(m.group(2))
    else:
        m = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
        if not m:
            return None
        hh, mm = int(m.group(1)), int(m.group(2))
        if hh > 23 or mm > 59:
            return None
    cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    while cand <= now:
        cand += timedelta(days=1)
    return cand


# claude.ai surfaces the rolling 5h window reset on the usage page as a RELATIVE
# string ("Resets in 30 min") under "Plan usage limits". The weekly cap shows as
# "Resets <Day> H:MM" -- which we ignore (it has no " in ").
USAGE_URL = "https://claude.ai/settings/usage"


def _parse_relative(s: str) -> timedelta | None:
    """'30 min' / '2 hours 15 min' / '1 hour' -> timedelta. None if unparseable."""
    s = s.lower()
    h = re.search(r"(\d+)\s*(?:hours?|hrs?)", s)
    mi = re.search(r"(\d+)\s*min", s)
    if not h and not mi:
        if "less than" in s or "moment" in s or "soon" in s:
            return timedelta(0)
        return None
    return timedelta(hours=int(h.group(1)) if h else 0,
                     minutes=int(mi.group(1)) if mi else 0)


def _scrape_reset(page) -> datetime | None:
    """Open the usage page and read the rolling 5h window reset ('Resets in X').
    Returns an absolute datetime (now + X), or None if it isn't shown."""
    try:
        page.goto(USAGE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3_500)
        text = page.inner_text("body")
    except Exception as e:
        log(f"Usage page failed to load: {e!r}")
        return None
    m = re.search(r"resets?\s+in\s+([^\n]+)", text, re.I)
    if m:
        dur = _parse_relative(m.group(1))
        if dur is not None:
            reset = datetime.now() + dur
            log(f"Usage page: 'Resets in {m.group(1).strip()[:30]}' -> reset {reset:%Y-%m-%d %H:%M}")
            return reset
    log("Usage page loaded but no rolling 'Resets in ...' found.")
    return None


def _write_anchor(open_dt: datetime) -> None:
    """Write the window-open anchor and show the derived reset, so you can see
    last_reset.txt update."""
    window = rs.load_config().window
    LAST_RESET_FILE.write_text(open_dt.isoformat(timespec="seconds"), encoding="utf-8")
    log(f"last_reset.txt updated -> window open {open_dt:%Y-%m-%d %H:%M} "
        f"(resets {(open_dt + window):%Y-%m-%d %H:%M})")


def _rearm() -> None:
    """Re-pin the next send + ping triggers to the just-updated anchor. Runs the
    PowerShell brain with no console window. Non-fatal: a failed re-arm is caught
    by the at-logon watchdog and the next run, so it must never crash the send."""
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(REARM_SCRIPT)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=90, capture_output=True, text=True,
        )
        log("Re-armed next send + ping triggers.")
    except Exception as e:
        log(f"Re-arm failed (non-fatal): {e!r}")


def _smart_sync(page) -> None:
    """The self-syncing scheduled routine. Reads the usage page and keeps
    last_reset.txt true, sending a message only when it actually opens a window:

      * window active (reset > 1 min away): record the anchor, no wasted send.
      * reset < 1 min away: FAIL-SAFE -- wait past the reset, then send so the
        message opens the NEW window (never a dying one).
      * no reset shown (window expired/inactive): send to open a window, re-read.
    """
    window = rs.load_config().window
    reset = _scrape_reset(page)

    if reset is not None:
        secs = (reset - datetime.now()).total_seconds()
        if secs >= 60:
            log(f"Window active; resets in {secs/60:.0f} min. Recording anchor, no send.")
            _write_anchor(reset - window)
            return
        wait_s = max(secs, 0) + 5   # a few seconds past the reset
        log(f"Reset in {secs:.0f}s (<1 min). Fail-safe: waiting {wait_s:.0f}s so the "
            f"send opens the new window.")
        page.wait_for_timeout(int(wait_s * 1000))
    else:
        log("No reset shown (window not active). Sending a message to open a window.")

    # Send (reused chat), then read the fresh window's reset and anchor to it.
    send_message(page)
    reset = _scrape_reset(page)
    if reset is not None:
        _write_anchor(reset - window)
    else:
        log("Usage page still unreadable after send; anchoring to now.")
        _write_anchor(datetime.now())


def run_autosync(reset_str: str | None) -> None:
    """Re-sync the shared anchor. With an explicit reset time, anchor = reset -
    window. Without one, scrape claude.ai; if no reset is shown, send a message
    to open a fresh window and anchor to that send."""
    window = rs.load_config().window

    if reset_str:
        dt = _parse_reset_clock(reset_str)
        if not dt:
            log(f"Could not parse {reset_str!r}. Use HH:MM or 'H:MM AM/PM'.")
            sys.exit(1)
        _write_anchor(dt - window)
        return

    if not PROFILE_DIR.exists():
        log("No saved session found. Run first:  uv run python autosend.py --login")
        sys.exit(1)

    with sync_playwright() as p:
        ctx = open_context(p, hidden=HEADLESS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(NEW_CHAT_URL, wait_until="domcontentloaded")
            page.locator(EDITOR_SELECTOR).first.wait_for(state="visible", timeout=30_000)

            dt = _scrape_reset(page)
            if dt:
                _write_anchor(dt - window)
                return

            log("No reset time on the page (no active limit, or window not begun). "
                "Sending a message to open a fresh window, then re-checking.")
            send_message(page)            # this also stamps last_reset.txt = now
            page.wait_for_timeout(2_000)
            dt2 = _scrape_reset(page)
            if dt2:
                _write_anchor(dt2 - window)
            else:
                log("Still no reset time shown; anchored to this send (now). If you "
                    "were mid-window, correct with:  autosend.py --autosync <reset HH:MM>")
        except PWTimeout:
            log("Could not load claude.ai (logged out?). Try  uv run python autosend.py --login")
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Send messages to claude.ai on a schedule.")
    parser.add_argument("--login", action="store_true",
                        help="Open a visible browser to log in once and save the session.")
    parser.add_argument("--test", action="store_true",
                        help="Send one message right now (visible) to verify the setup, then exit.")
    parser.add_argument("--once", action="store_true",
                        help="Send one message headless and exit. Used by Windows Task Scheduler.")
    parser.add_argument("--autosync", nargs="?", const="", default=None, metavar="HH:MM",
                        help="Re-anchor the schedule. With a reset time (e.g. --autosync 12:39) "
                             "it uses that; bare --autosync scrapes claude.ai, sending a message "
                             "to open a window if none is active.")
    args = parser.parse_args()

    if args.login:
        do_login()
    elif args.test:
        run_test()
    elif args.once:
        run_once()
    elif args.autosync is not None:
        run_autosync(args.autosync or None)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
