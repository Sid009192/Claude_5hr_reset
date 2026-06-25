"""
digest.py
=========
Daily plan-your-day digest of Claude windows, in the prepare-then-publish style:

    uv run python digest.py --prep              # stage TODAY's digest (default)
    uv run python digest.py --prep tomorrow     # stage TOMORROW's digest
    uv run python digest.py --publish           # publish TODAY (Telegram + calendar)
    uv run python digest.py --publish tomorrow  # publish TOMORROW
    uv run python digest.py                     # (no flag) print TODAY's digest

Both --prep and --publish take an optional day: ``today`` (default) or
``tomorrow``. Prep is silent (just stages a file, tagged with the day it is
for); publish sends to Telegram AND pushes that SAME day's windows to Google
Calendar -- both keyed off one resolved day, so the two channels can never
disagree. Run one-shot from Windows Task Scheduler. Wallpaper rendering will
hook into publish later.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import reset_schedule as rs
import notify_telegram
import notify_calendar

# The digest contains emoji; make stdout tolerate it on a cp1252 console.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STAGED = Path(__file__).parent / "digest_staged.txt"


def build_digest(day: date, cfg: rs.Config, anchor: datetime) -> str:
    wins = rs.windows_for_day(day, cfg, anchor)
    lead = max(cfg.lead_minutes)  # golden slot = longest lead before reset
    lines = [f"*Claude windows — {day:%a %d %b}*", ""]
    if not wins:
        lines.append("_(no windows)_")
    for w in wins:
        golden = w.reset - timedelta(minutes=lead)
        o = w.open.strftime("%I:%M %p").lstrip("0")
        r = w.reset.strftime("%I:%M %p").lstrip("0")
        g = golden.strftime("%I:%M %p").lstrip("0")
        lines.append(f"🟢 {o} → {r}")
        lines.append(f"    🔥 *heavy-work {g} → {r}*")
    lines += ["", "_Pings 2h & 1.5h before each reset · quiet 3–9 AM._"]
    return "\n".join(lines)


def _resolve_day(which: str) -> date:
    """'today' | 'tomorrow' -> the matching date."""
    return date.today() + timedelta(days=1) if which == "tomorrow" else date.today()


def _read_staged() -> tuple[date, str] | None:
    """Return (staged_day, text) from the staged file, or None if absent/legacy.
    The staged file's first line is the ISO day it was prepped for."""
    if not STAGED.exists():
        return None
    head, _, body = STAGED.read_text(encoding="utf-8").partition("\n")
    try:
        return date.fromisoformat(head.strip()), body
    except ValueError:
        return None  # no day header (legacy stage) -> treat as not usable


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily Claude window digest.")
    ap.add_argument("--prep", nargs="?", const="today", choices=["today", "tomorrow"],
                    default=None, metavar="WHEN",
                    help="Stage the digest for today (default) or tomorrow.")
    ap.add_argument("--publish", nargs="?", const="today", choices=["today", "tomorrow"],
                    default=None, metavar="WHEN",
                    help="Publish (Telegram + calendar) the digest for today (default) or tomorrow.")
    args = ap.parse_args()

    cfg = rs.load_config()
    anchor = rs.load_anchor(cfg)

    if args.prep is not None:
        day = _resolve_day(args.prep)
        STAGED.write_text(f"{day.isoformat()}\n{build_digest(day, cfg, anchor)}",
                          encoding="utf-8")
        print(f"[digest] staged for {day:%a %d %b}.")
    elif args.publish is not None:
        day = _resolve_day(args.publish)
        # Reuse the staged text only if it was prepped for THIS day; else rebuild
        # fresh so Telegram and calendar always reflect the requested day.
        staged = _read_staged()
        if staged and staged[0] == day:
            text = staged[1]
        else:
            text = build_digest(day, cfg, anchor)
            if staged:
                print(f"[digest] staged day {staged[0]:%d %b} != {day:%d %b}; rebuilt fresh.")
        ok = notify_telegram.send(text)
        # Push the SAME day's windows to Google Calendar (if enabled). Kept
        # separate from Telegram so a calendar hiccup never costs the ping.
        n = 0
        if cfg.raw.get("calendar", {}).get("sync_on_publish", False):
            n = notify_calendar.sync_day(day, cfg, anchor)
        print(f"[digest] published {day:%a %d %b} telegram={'ok' if ok else 'skip/fail'} "
              f"calendar={n} event(s)")
    else:
        print(build_digest(date.today(), cfg, anchor))


if __name__ == "__main__":
    main()
