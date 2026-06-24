"""Telegram delivery module for the 5-hour-window notifier.

This is the Telegram side of the notification layer. It is invoked ONCE per
call by Windows Task Scheduler -- there is NO long-running process and no
shared state to maintain. Each run reads credentials, fires a single HTTP POST
to the Telegram Bot API, and exits.

Design constraints:
  * Standard library ONLY -- `urllib.request` for the HTTP POST and `tomllib`
    for config. No third-party deps (the `requests` library is intentionally
    avoided so the venv stays minimal and Task Scheduler stays reliable).
  * `send()` must NEVER raise: a notifier that crashes the scheduler task is
    worse than one that quietly returns False. All failure paths print a clear
    reason and return False.

Credentials are SECRET and live in a gitignored `.env` file (never committed) as
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Real environment variables take
precedence over the file. See `.env.example` for the template. Until both are
set, `send()` reports the missing creds and returns False without hitting the API.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# .env sits next to this module in the project root. Resolve relative to __file__
# so the path is correct regardless of the scheduler's working dir.
ENV_PATH = Path(__file__).resolve().parent / ".env"

# Telegram Bot API endpoint template; {bot_token} is substituted at call time.
API_URL_TEMPLATE = "https://api.telegram.org/bot{bot_token}/sendMessage"

# Network timeout (seconds). Task Scheduler fire-and-forget -- keep it short so a
# hung connection can't pin the task open.
HTTP_TIMEOUT = 10


def _read_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser (stdlib only). Ignores blanks and #comments,
    strips optional surrounding quotes. Never raises on a missing/bad file."""
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
        print(f"[telegram] Could not read {path}: {exc}")
    return values


def _load_credentials() -> tuple[str, str]:
    """Read (bot_token, chat_id) from the environment, falling back to .env.

    Real env vars win over the file (handy for CI/overrides). Returns empty
    strings for anything missing -- never raises.
    """
    file_vals = _read_env_file(ENV_PATH)
    bot_token = (os.environ.get("TELEGRAM_BOT_TOKEN")
                 or file_vals.get("TELEGRAM_BOT_TOKEN", "")).strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID")
               or file_vals.get("TELEGRAM_CHAT_ID", "")).strip()
    return bot_token, chat_id


def _post(bot_token: str, chat_id: str, text: str, parse_mode: str) -> tuple[bool, str]:
    """One POST attempt. Returns (ok, info). info is empty on success, else a
    short reason. parse_mode="" sends plain text (no entity parsing)."""
    fields = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        fields["parse_mode"] = parse_mode

    payload = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        API_URL_TEMPLATE.format(bot_token=bot_token),
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return False, f"HTTP {exc.code} {exc.reason}: {body}"
    except urllib.error.URLError as exc:
        return False, f"Network error: {exc.reason}"
    except Exception as exc:  # noqa: BLE001 -- never raise.
        return False, f"Unexpected error: {exc}"

    # A 200 can still carry ok=false; parse and verify.
    try:
        if not json.loads(body).get("ok", False):
            return False, f"ok=false: {body}"
    except json.JSONDecodeError:
        return False, f"unparseable response: {body}"
    return True, ""


def send(text: str, parse_mode: str = "Markdown") -> bool:
    """Send `text` to the configured Telegram chat. Returns True on success,
    False if creds are missing or the API call fails. Never raises.

    If Markdown parsing fails (stray * or _ in dynamic content), retries once as
    plain text so a formatting slip never costs you the whole notification."""
    bot_token, chat_id = _load_credentials()
    if not bot_token or not chat_id:
        print(
            "[telegram] Credentials missing. Set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID in .env (copy .env.example), then re-run."
        )
        return False

    ok, info = _post(bot_token, chat_id, text, parse_mode)
    if ok:
        return True

    # Markdown entity errors -> resend as plain text rather than drop it.
    if parse_mode and "parse entities" in info:
        print(f"[telegram] Markdown parse failed, retrying as plain text. ({info})")
        ok, info = _post(bot_token, chat_id, text, "")
        if ok:
            return True

    print(f"[telegram] {info}")
    return False


if __name__ == "__main__":
    ok = send("✅ Telegram test from notify_telegram.py")
    if ok:
        print("[telegram] Test message sent successfully.")
    else:
        print("[telegram] Test message NOT sent (see reason above).")
