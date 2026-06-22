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

2. Run the scheduler (keeps sending on the configured schedule):
       uv run python autosend.py

Stop it any time with Ctrl+C.
"""

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# --------------------------------------------------------------------------- #
# CONFIG  --  edit these to taste
# --------------------------------------------------------------------------- #

# The message that gets sent each time.
MESSAGE = "hi"

# First send happens today at this HH:MM (24-hour clock), then repeats.
FIRST_RUN_HOUR = 19      # 7 PM
FIRST_RUN_MINUTE = 20    # :20  -> 7:20 PM

# Gap between sends: every 5 hours and 2 minutes.
INTERVAL = timedelta(hours=5, minutes=2)

# Hide the browser for --once / loop modes?
# claude.ai blocks true headless, so True does NOT use headless -- instead it
# runs a REAL window parked off-screen (invisible to you, accepted by claude.ai).
# Set to False only if you want to watch the window on-screen.
HEADLESS = True

# Where the logged-in browser session is stored (so you log in only once).
PROFILE_DIR = Path(__file__).parent / "pw-profile"

# Remembers the single conversation we reuse, so we don't clutter chat history
# with a new chat every time. Deleted/invalid chats are recreated automatically.
CONVERSATION_FILE = Path(__file__).parent / "conversation_url.txt"

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
    # Give the request a moment to actually fire before we move on.
    page.wait_for_timeout(3_000)

    # If this was a new chat, claude.ai navigates to /chat/<id>. Remember it so
    # every future send reuses this same conversation (no history clutter).
    if is_new_chat and "/chat/" in page.url:
        CONVERSATION_FILE.write_text(page.url, encoding="utf-8")
        log(f"Saved conversation for reuse: {page.url}")


def next_run_after(now: datetime) -> datetime:
    """First scheduled time today at FIRST_RUN_HOUR:MINUTE, advanced by INTERVAL
    until it is in the future."""
    run = now.replace(
        hour=FIRST_RUN_HOUR, minute=FIRST_RUN_MINUTE, second=0, microsecond=0
    )
    while run <= now:
        run += INTERVAL
    return run


def sleep_until(target: datetime) -> None:
    """Sleep until target, waking every 30s so Ctrl+C stays responsive and we
    can print a countdown."""
    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            return
        log(f"Next send at {target:%Y-%m-%d %H:%M:%S}  (in {remaining/3600:.2f} h)")
        time.sleep(min(remaining, 30))


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
            send_message(page)
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


def run_loop() -> None:
    if not PROFILE_DIR.exists():
        log("No saved session found. Run first:  uv run python autosend.py --login")
        sys.exit(1)

    with sync_playwright() as p:
        ctx = open_context(p, hidden=HEADLESS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Verify we're actually logged in before committing to the loop.
        try:
            page.goto(NEW_CHAT_URL, wait_until="domcontentloaded")
            page.locator(EDITOR_SELECTOR).first.wait_for(state="visible", timeout=30_000)
        except PWTimeout:
            log("Could not find the chat box. You may be logged out, or claude.ai "
                "is blocking headless mode.")
            log("Fix: run  uv run python autosend.py --login  (and/or set HEADLESS = False).")
            ctx.close()
            sys.exit(1)

        log("Logged in and ready. Scheduler running. Press Ctrl+C to stop.")

        next_run = next_run_after(datetime.now())
        try:
            while True:
                sleep_until(next_run)
                try:
                    send_message(page)
                except Exception as e:  # don't let one failure kill the loop
                    log(f"Send failed: {e!r}. Will try again next cycle.")
                next_run += INTERVAL
        except KeyboardInterrupt:
            log("Stopped by user.")
        finally:
            ctx.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Send messages to claude.ai on a schedule.")
    parser.add_argument("--login", action="store_true",
                        help="Open a visible browser to log in once and save the session.")
    parser.add_argument("--test", action="store_true",
                        help="Send one message right now (visible) to verify the setup, then exit.")
    parser.add_argument("--once", action="store_true",
                        help="Send one message headless and exit. Used by Windows Task Scheduler.")
    args = parser.parse_args()

    if args.login:
        do_login()
    elif args.test:
        run_test()
    elif args.once:
        run_once()
    else:
        run_loop()


if __name__ == "__main__":
    main()
