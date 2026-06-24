"""Windows toast notification delivery for the Claude reset notifier.

This module is the Windows toast layer of the notification system. It is
invoked ONCE per call by Windows Task Scheduler -- there is no long-running
process. A script runs, pops a single toast, and exits immediately. So the
code here must produce a visible toast from a one-shot, non-interactive
process (no message loop, no event pump to wait on).

We use the maintained `windows-toasts` library. To get a sensible app label
on the toast -- and, importantly, to make toasts display reliably when fired
from a background / Task-Scheduler context -- we register a stable
AppUserModelID (AUMID). `WindowsToaster(applicationText)` builds its notifier
via `create_toast_notifier_with_id(applicationText)`, so the string we pass in
*is* the AUMID the toast is attributed to.

Everything is wrapped to fail gracefully: a broken or missing toast backend
prints one clear line and returns, never raising, so a failed notification can
never crash the caller that scheduled it.
"""

from __future__ import annotations

# Stable AppUserModelID. Using a constant (rather than a fresh/random label)
# keeps toasts grouped under one app identity and lets Windows reliably surface
# them from a one-shot background process.
APP_USER_MODEL_ID: str = "Claude.ResetNotifier"


def notify(title: str, message: str) -> None:
    """Show a Windows toast. Must work when called from a one-shot background process."""
    try:
        # Imported lazily so a missing dependency degrades to a printed message
        # instead of an import-time crash for any caller of this module.
        from windows_toasts import Toast, WindowsToaster
    except ImportError:
        print("[notify_toast] windows-toasts not installed; skipping toast.")
        return

    try:
        # The applicationText doubles as the AUMID (see module docstring).
        toaster = WindowsToaster(APP_USER_MODEL_ID)
        toast = Toast()
        toast.text_fields = [title, message]
        # show_toast hands the notification to Windows synchronously; the toast
        # remains visible after this one-shot process exits.
        toaster.show_toast(toast)
    except Exception as exc:  # noqa: BLE001 -- a failed toast must never crash the caller.
        print(f"[notify_toast] failed to show toast: {exc}")
        return


if __name__ == "__main__":
    # Direct-run smoke test for the Task-Scheduler delivery path.
    notify("Claude reset in 2h", "Heavy-work window starting — load up.")
