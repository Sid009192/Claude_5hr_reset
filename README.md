# Claude auto-sender

Sends a message to **claude.ai** on a fixed schedule using a dedicated,
separate Playwright browser session. It runs in the background and **never
takes over your real mouse or keyboard** — you can keep using your laptop
normally.

## Setup (already done)

```bash
uv venv
uv add playwright
uv run playwright install chromium
```

## 1. Log in once

```bash
uv run python autosend.py --login
```

A browser window opens. Sign in to Claude, then press **Enter** in the
terminal to save the session. You only do this once (re-run if you ever get
logged out).

## 2. Run the scheduler

```bash
uv run python autosend.py
```

- First send: **today at 7:20 PM**
- Then every **5 hours 2 minutes** after that
- Message sent: `hi`
- Stop any time with **Ctrl+C**

## Configuration

Edit the `CONFIG` block at the top of [`autosend.py`](autosend.py):

| Setting | Meaning |
|---|---|
| `MESSAGE` | Text to send each time |
| `FIRST_RUN_HOUR` / `FIRST_RUN_MINUTE` | When the first send happens today |
| `INTERVAL` | Gap between sends (default 5h 2m) |
| `HEADLESS` | `True` = hidden browser (background). Set `False` if claude.ai blocks headless. |

## Notes

- This drives its **own** claude.ai session, not your desktop app or the PWA
  window you have open. That's what lets it run without interfering.
- The computer must be **on and not logged out of Windows** for it to run.
- Closing the terminal stops it. To survive reboots, wire it into Windows
  Task Scheduler (ask if you want that).
