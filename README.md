# Claude Auto-Sender

Sends a message to **claude.ai** on a fixed schedule, in the background, using a
dedicated browser session driven by Playwright. It runs **without taking over
your mouse or keyboard** — the browser is parked off-screen — so you can keep
using your computer normally.

By default it sends one message at your chosen start time, then repeats on a
fixed interval (e.g. every 5 hours 2 minutes). All messages go into a **single
reused chat**, so your history stays clean.

> Windows only (uses Windows Task Scheduler). Requires [uv](https://docs.astral.sh/uv/).

---

## How it works

```
Windows Task Scheduler  --(on your schedule)-->  python autosend.py --once
        |
        v
  Playwright opens its own Chrome (saved login profile), parked off-screen
        |
        v
  Opens the reused chat (or creates one the first time) and sends your message
```

- **Playwright, not PyAutoGUI** — it drives its own browser via the page, so it
  never grabs your real mouse/keyboard.
- **Headed but off-screen** — claude.ai blocks headless browsers, so the window
  is a real one moved far off-screen (invisible to you, accepted by the site).
- **Task Scheduler, not an always-on loop** — nothing runs all day; it survives
  reboots and the OS owns the timing and power rules.

---

## Setup from scratch

### 1. Install dependencies

```bash
uv venv
uv add playwright
uv run playwright install --force chromium
```

> `--force` matters: a plain install can silently skip the actual browser
> download. After it runs, the Chromium executable should exist under
> `…\AppData\Local\ms-playwright\chromium-*\chrome-win64\chrome.exe`.

### 2. Log in once

```bash
uv run python autosend.py --login
```

A browser window opens. Sign in to Claude, then return to the terminal and press
**Enter** to save the session. You only do this once (re-run if you ever get
logged out). The login is stored in a local `pw-profile/` folder.

### 3. Verify it works

```bash
uv run python autosend.py --test    # sends one message in a VISIBLE window
uv run python autosend.py --once    # sends one message OFF-SCREEN (what the task uses)
```

After each, check claude.ai — a new message should appear in the reused chat.
`--once` shows only a brief taskbar flicker and no visible tab. That's correct.

### 4. Schedule it

Open `setup_task.ps1` and set **your** first-run time at the top:

```powershell
$StartHour      = 9     # 24-hour clock: first run today at this hour
$StartMinute    = 0
$IntervalHours  = 5     # then repeat every...
$IntervalMinutes = 2
```

Then register the task (no admin needed):

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_task.ps1
```

It auto-detects its own folder, so there are no paths to edit. Confirm:

```powershell
Get-ScheduledTask -TaskName "Claude Auto Sender" | Get-ScheduledTaskInfo
```

`NextRunTime` shows when it fires next. After your chosen start time, each
subsequent run lands one interval later, automatically.

---

## Configuration

Top of [`autosend.py`](autosend.py):

| Setting | Meaning |
|---|---|
| `MESSAGE` | The text sent each time |
| `HEADLESS` | `True` = off-screen window (invisible). `False` = on-screen window |
| `EDITOR_SELECTOR` | The claude.ai chat input selector |

Top of [`setup_task.ps1`](setup_task.ps1): start time and repeat interval.

Script modes:

| Command | What it does |
|---|---|
| `--login` | One-time visible login; saves the session |
| `--test` | Send one message in a visible window (to eyeball it) |
| `--once` | Send one message off-screen, then exit (used by Task Scheduler) |
| *(no flag)* | Long-running loop (legacy; Task Scheduler replaces this) |

---

## Notes

- It drives its **own** claude.ai session, separate from any Claude app/PWA you
  have open. That separation is what lets it run without interfering.
- The computer must be **on and logged in** at fire time (a locked screen is
  fine). It will **not** wake the machine from sleep; a fire missed during sleep
  runs shortly after you wake it.
- If you move the project folder, just re-run `setup_task.ps1`.
- Remove the task: `Unregister-ScheduledTask -TaskName "Claude Auto Sender" -Confirm:$false`

---

## Disclaimer

This automates the claude.ai web UI with your own logged-in session. It's
intended for personal, low-volume use. For anything larger or production-grade,
use the official Anthropic API instead.
