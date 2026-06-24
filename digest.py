"""
digest.py
=========
Daily plan-your-day digest of Claude windows, in the prepare-then-publish style:

    uv run python digest.py --prep       # ~8 PM: build TOMORROW's digest, stage it
    uv run python digest.py --publish    # 12 AM: send the staged digest via Telegram
    uv run python digest.py              # (no flag) print TODAY's digest to stdout

Both run one-shot from Windows Task Scheduler. Prep is silent (just stages a
file); publish is what actually reaches you at midnight. Wallpaper rendering will
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily Claude window digest.")
    ap.add_argument("--prep", action="store_true", help="Stage tomorrow's digest.")
    ap.add_argument("--publish", action="store_true", help="Send the staged digest.")
    args = ap.parse_args()

    cfg = rs.load_config()
    anchor = rs.load_anchor(cfg)

    if args.prep:
        day = date.today() + timedelta(days=1)
        STAGED.write_text(build_digest(day, cfg, anchor), encoding="utf-8")
        print(f"[digest] staged for {day:%a %d %b}.")
    elif args.publish:
        text = STAGED.read_text(encoding="utf-8") if STAGED.exists() \
            else build_digest(date.today(), cfg, anchor)
        ok = notify_telegram.send(text)
        # Also push today's heavy-work windows to Google Calendar (if enabled).
        # Kept separate from Telegram so a calendar hiccup never costs the ping.
        n = 0
        if cfg.raw.get("calendar", {}).get("sync_on_publish", False):
            n = notify_calendar.sync_day(date.today(), cfg, anchor)
        print(f"[digest] published telegram={'ok' if ok else 'skip/fail'} "
              f"calendar={n} event(s)")
    else:
        print(build_digest(date.today(), cfg, anchor))


if __name__ == "__main__":
    main()
