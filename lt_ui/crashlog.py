"""Write down why the program died, somewhere a person can find it.

PySide6 does not let a Python exception escape a slot quietly. An unhandled
one ends the process through `abort()`, and on Windows that means no console,
no dialog and no file: the window simply vanishes. All the user can report is
"it closed", and the cause has to be dug out of a crash dump -- which is how
this module came to exist.

So every unhandled exception is written down before anything else happens:
the interpreter's own, the ones that end a thread, and the "unraisable" kind
Python reports when a callback fails somewhere it cannot propagate from, such
as during teardown. The previous hook is always called afterwards, so stderr
keeps working exactly as it did.

Writing must never be the thing that fails. Every step is guarded: a log that
cannot be written is a shame, but a log that takes the program down with it
would be worse than having none.
"""

from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

#: Kept small enough to paste into a message, large enough to hold the run
#: before the one that mattered. Past this the file starts again.
MAX_BYTES = 256 * 1024

LOG_NAME = "crash.log"

_installed = False


def log_path(folder: Path | str | None = None) -> Path:
    """Where the record goes: beside the user's settings."""
    if folder is not None:
        return Path(folder) / LOG_NAME
    from .paths import user_data_dir

    return user_data_dir() / LOG_NAME


def record(text: str, folder: Path | str | None = None) -> Path | None:
    """Append one entry. Returns the file written, or None if it could not be."""
    target = log_path(folder)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n===== {stamp} =====\n{text.rstrip()}\n"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > MAX_BYTES:
            target.unlink()
        with target.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write(entry)
            fh.flush()
        return target
    except (OSError, ValueError):
        return None


def _describe(kind, value, tb) -> str:
    try:
        return "".join(traceback.format_exception(kind, value, tb))
    except Exception:  # noqa: BLE001 -- formatting must not be the failure
        return f"{kind!r}: {value!r}"


def install(folder: Path | str | None = None) -> None:
    """Start recording. Safe to call more than once."""
    global _installed
    if _installed:
        return
    _installed = True

    previous_except = sys.excepthook
    previous_thread = getattr(threading, "excepthook", None)
    previous_unraisable = getattr(sys, "unraisablehook", None)

    def on_exception(kind, value, tb):
        record("unhandled exception\n" + _describe(kind, value, tb), folder)
        previous_except(kind, value, tb)

    def on_thread_exception(args):
        name = getattr(args.thread, "name", "?")
        record(
            f"unhandled exception in thread {name}\n"
            + _describe(args.exc_type, args.exc_value, args.exc_traceback),
            folder,
        )
        if previous_thread is not None:
            previous_thread(args)

    def on_unraisable(args):
        where = getattr(args, "object", None)
        record(
            f"unraisable exception in {where!r}\n"
            + _describe(args.exc_type, args.exc_value, args.exc_traceback),
            folder,
        )
        if previous_unraisable is not None:
            previous_unraisable(args)

    sys.excepthook = on_exception
    if previous_thread is not None:
        threading.excepthook = on_thread_exception
    if previous_unraisable is not None:
        sys.unraisablehook = on_unraisable
