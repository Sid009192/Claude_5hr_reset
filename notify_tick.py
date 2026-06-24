"""
notify_tick.py
==============
One-shot ping fired by Windows Task Scheduler a fixed number of minutes before a
reset. It is NOT a loop -- Task Scheduler runs it, it pings, it exits.

    uv run python notify_tick.py 120     # 2h heavy-work warning
    uv run python notify_tick.py 90      # 1.5h heavy-work warning

It reads the REAL next reset from last_reset.txt (via reset_schedule), so the
message is accurate even if the trigger fires a couple of minutes off the grid.
During quiet hours it suppresses itself silently.

Sends to BOTH channels: Windows toast (at the desk) + Telegram (anywhere).
A failure in either channel never crashes the other -- both delivery modules
swallow their own errors and return.
"""

from __future__ import annotations

import sys
from datetime import datetime

import reset_schedule as rs
import notify_toast
import notify_telegram

# Title per lead so the two pings are distinguishable at a glance.
_HEADLINES = {120: "Claude resets in ~2h", 90: "Claude resets in ~1.5h"}


def main() -> None:
    lead = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    cfg = rs.load_config()
    anchor = rs.load_anchor(cfg)
    now = datetime.now()

    if rs.is_quiet(now, cfg):
        print(f"[tick] quiet hours ({now:%H:%M}) -- suppressed.")
        return

    reset = rs.next_reset(now, cfg, anchor)
    mins = round((reset - now).total_seconds() / 60)
    when = reset.strftime("%I:%M %p").lstrip("0")

    headline = _HEADLINES.get(lead, f"Claude resets in ~{mins} min")
    body = f"Reset at {when} (~{mins} min). Heavy-work window — go hard, credits refill then."

    notify_toast.notify(headline, body)
    ok = notify_telegram.send(f"⏳ *{headline}*\n{body}")
    print(f"[tick] lead={lead} reset={when} toast=sent telegram={'ok' if ok else 'skip/fail'}")


if __name__ == "__main__":
    main()
