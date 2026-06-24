"""
reset_schedule.py
=================
Single source of truth for *when* Claude usage windows open and reset.

Two distinct durations matter, and conflating them caused a 2-minute slip:

  * window  = how long a usage window lasts. A window that OPENS at time O has
              its quota RESET at  O + window  (default 5h00m). This is the time
              you actually plan around.
  * send_interval = the auto-sender's cadence. The next window OPENS at
              O + send_interval (default 5h00m30s: 5h plus a small buffer so the
              send lands just after the old window expires, never inside it).

So opens and resets are two interleaved sequences:

    open_k  = anchor + k * send_interval
    reset_k = open_k + window

``anchor`` is the last REAL window open (= last send), stamped to
``last_reset.txt`` by autosend.py on every send and by ``--autosync``. Because
every send re-stamps it, the schedule self-corrects -- there is no accumulating
projection drift.

Run it directly to eyeball the schedule:
    uv run python reset_schedule.py                 # today
    uv run python reset_schedule.py --day tomorrow
    uv run python reset_schedule.py --next          # next reset + ping times
    uv run python reset_schedule.py --reset-iso     # machine-readable (for .ps1)
"""

from __future__ import annotations

import argparse
import math
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_FILE = HERE / "notify_config.local.toml"
LAST_RESET_FILE = HERE / "last_reset.txt"

# Fallbacks used only if the config file is missing a value.
DEFAULT_WINDOW_MINUTES = 300            # 5h00m -- reset = open + this
DEFAULT_SEND_INTERVAL_SECONDS = 18030   # 5h00m30s -- next open = open + this
DEFAULT_LEAD_MINUTES = [120, 90]        # ping 2h and 1.5h before each reset
DEFAULT_QUIET = ("03:00", "09:00")      # no pings in this window


@dataclass(frozen=True)
class Config:
    window: timedelta          # reset  = open + window
    send_interval: timedelta   # next open = open + send_interval
    lead_minutes: list[int]
    quiet_start: time
    quiet_end: time
    raw: dict


@dataclass(frozen=True)
class Window:
    """One usage window: fresh quota at ``open``, refreshes again at ``reset``."""
    open: datetime
    reset: datetime

    def ping_times(self, cfg: Config) -> list[tuple[int, datetime]]:
        """(lead_minutes, when_to_ping) for this window's reset."""
        return [(lead, self.reset - timedelta(minutes=lead)) for lead in cfg.lead_minutes]


# --------------------------------------------------------------------------- #
# Config + anchor
# --------------------------------------------------------------------------- #

def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def load_config() -> Config:
    data: dict = {}
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("rb") as fh:
            data = tomllib.load(fh)
    window_min = data.get("window_minutes", DEFAULT_WINDOW_MINUTES)
    interval_sec = data.get("send_interval_seconds", DEFAULT_SEND_INTERVAL_SECONDS)
    leads = data.get("pings", {}).get("lead_minutes", DEFAULT_LEAD_MINUTES)
    quiet = data.get("quiet_hours", {})
    return Config(
        window=timedelta(minutes=window_min),
        send_interval=timedelta(seconds=interval_sec),
        lead_minutes=list(leads),
        quiet_start=_parse_hhmm(quiet.get("start", DEFAULT_QUIET[0])),
        quiet_end=_parse_hhmm(quiet.get("end", DEFAULT_QUIET[1])),
        raw=data,
    )


def load_anchor(cfg: Config | None = None) -> datetime:
    """The last real window open (a send time). Prefers last_reset.txt (ground
    truth), falls back to ``seed_anchor`` in the config for first-time bootstrap."""
    if LAST_RESET_FILE.exists():
        txt = LAST_RESET_FILE.read_text(encoding="utf-8").strip()
        if txt:
            return datetime.fromisoformat(txt)
    cfg = cfg or load_config()
    seed = cfg.raw.get("seed_anchor")
    if seed:
        return datetime.fromisoformat(seed)
    raise SystemExit(
        "No anchor available: last_reset.txt is missing and no 'seed_anchor' is "
        "set in notify_config.local.toml. Let autosend.py run once, or seed it."
    )


# --------------------------------------------------------------------------- #
# Schedule math
#   open_k  = anchor + k * send_interval
#   reset_k = open_k + window
# --------------------------------------------------------------------------- #

def next_reset(now: datetime, cfg: Config, anchor: datetime) -> datetime:
    """The first reset strictly after ``now``."""
    delta = now - anchor - cfg.window
    k = 0 if delta < timedelta(0) else math.floor(delta / cfg.send_interval) + 1
    return anchor + k * cfg.send_interval + cfg.window


def next_open(now: datetime, cfg: Config, anchor: datetime) -> datetime:
    """The first window-open (send time) strictly after ``now``."""
    k = math.floor((now - anchor) / cfg.send_interval) + 1
    o = anchor + k * cfg.send_interval
    while o <= now:
        o += cfg.send_interval
    return o


def opens_between(start: datetime, end: datetime, cfg: Config,
                  anchor: datetime) -> list[datetime]:
    """All window opens O_k with start <= O_k < end."""
    k0 = math.ceil((start - anchor) / cfg.send_interval)
    out: list[datetime] = []
    o = anchor + k0 * cfg.send_interval
    while o < end:
        if o >= start:
            out.append(o)
        o += cfg.send_interval
    return out


def windows_for_day(day: date, cfg: Config, anchor: datetime) -> list[Window]:
    """Windows whose ``open`` falls on the given calendar day (midnight to
    midnight). Each window's reset is open + window."""
    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    return [Window(open=o, reset=o + cfg.window)
            for o in opens_between(day_start, day_end, cfg, anchor)]


def is_quiet(dt: datetime, cfg: Config) -> bool:
    """True if dt's time-of-day is inside the quiet range (pings suppressed)."""
    t = dt.time()
    qs, qe = cfg.quiet_start, cfg.quiet_end
    if qs <= qe:
        return qs <= t < qe
    return t >= qs or t < qe          # range wraps past midnight


# --------------------------------------------------------------------------- #
# CLI -- for eyeballing / verifying the schedule
# --------------------------------------------------------------------------- #

def _fmt(dt: datetime) -> str:
    return dt.strftime("%a %d %b %I:%M %p").replace(" 0", " ")


def _print_day(day: date, cfg: Config, anchor: datetime) -> None:
    wins = windows_for_day(day, cfg, anchor)
    print(f"\nWindows for {day:%A %d %b %Y}  (anchor: {_fmt(anchor)})")
    print("-" * 60)
    if not wins:
        print("  (none)")
        return
    lead = max(cfg.lead_minutes)
    for w in wins:
        golden = w.reset - timedelta(minutes=lead)
        print(f"  open {_fmt(w.open):<22} -> reset {_fmt(w.reset)}")
        print(f"       golden heavy-work slot: {_fmt(golden)} -> {_fmt(w.reset)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Show the Claude reset schedule.")
    ap.add_argument("--day", choices=["today", "tomorrow"], default="today")
    ap.add_argument("--next", action="store_true",
                    help="Show only the next reset and its ping times.")
    ap.add_argument("--reset-iso", action="store_true",
                    help="Print ONLY the next reset as ISO.")
    ap.add_argument("--arm-times", action="store_true",
                    help="Print next send + ping fire times as KEY=ISO (for schedule_rearm.ps1).")
    args = ap.parse_args()

    cfg = load_config()
    anchor = load_anchor(cfg)
    now = datetime.now()

    if args.reset_iso:
        print(next_reset(now, cfg, anchor).isoformat())
        return

    if args.arm_times:
        # SEND = next window-open; PING:<lead> = <lead> min before the soonest
        # reset that is still far enough ahead to give that lead.
        print(f"SEND={next_open(now, cfg, anchor).isoformat()}")
        for lead in cfg.lead_minutes:
            pt = next_reset(now + timedelta(minutes=lead), cfg, anchor) - timedelta(minutes=lead)
            print(f"PING:{lead}={pt.isoformat()}")
        return

    if args.next:
        nr = next_reset(now, cfg, anchor)
        print(f"Next reset: {_fmt(nr)}  (in {(nr - now).total_seconds()/3600:.2f} h)")
        for lead in cfg.lead_minutes:
            when = nr - timedelta(minutes=lead)
            quiet = " [QUIET -- suppressed]" if is_quiet(when, cfg) else ""
            print(f"  ping -{lead}m at {_fmt(when)}{quiet}")
        return

    day = date.today() if args.day == "today" else date.today() + timedelta(days=1)
    _print_day(day, cfg, anchor)


if __name__ == "__main__":
    main()
