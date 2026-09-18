"""Where this user's own data lives.

While the program runs from a source folder, keeping settings next to the code
is convenient and harmless. An installed copy is neither: `Program Files` is
not writable, and one folder of settings shared by everyone who signs in to
the machine is the wrong shape for something that holds a person's languages,
their history and their API key.

So user data goes where each platform keeps user data, and the program's own
folder holds only the program. The two things that stay behind are deliberate:

* **Models.** Gigabytes, identical for everyone, read-only in use. They belong
  with the installation, not copied into every profile.
* **Finished files.** They go wherever the user chose, which is the point of
  that setting.

`LINGUAFLOW_DATA` overrides all of this, for a portable copy on a memory stick
or for a test that must not touch a real profile.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Linguaflow"

#: The files that make up a user's state, as opposed to their output. Small,
#: and worth carrying across from an older layout.
STATE_FILES = ("settings.json", "history.json", "keys.dat")


def user_data_dir() -> Path:
    """The per-user folder for this application."""
    override = os.environ.get("LINGUAFLOW_DATA", "").strip()
    if override:
        return Path(override)

    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / APP_NAME


def actual_location(folder: Path) -> tuple[Path, bool]:
    """Where a folder really is, and whether that differs from its name.

    Python installed from the Microsoft Store runs inside a package sandbox
    and quietly redirects writes to `%APPDATA%` into its own LocalCache. The
    program then reports a path that File Explorer says does not exist, and a
    user looking for their settings finds nothing there. `resolve()` sees
    through it; the interface shows what it finds.

    A packaged build is an ordinary executable and is not redirected, so this
    is a development quirk -- but one that would send someone hunting.
    """
    try:
        real = folder.resolve()
    except OSError:
        return folder, False
    return real, real != folder


#: Where finished files go unless the user picks somewhere else.
OUTPUT_FOLDER = "translated"

#: The Windows identifier for the Videos folder. Asked of the system rather
#: than assembled from the home directory: it can be moved to another drive,
#: it is renamed in a localised Windows, and a guess would put a user's work
#: somewhere they do not look.
_FOLDERID_VIDEOS = "18989B1D-99B5-455B-841C-AB7C74E4DDFC"


def _known_folder(folder_id: str) -> Path | None:
    """Ask Windows where one of its own folders actually is."""
    if sys.platform != "win32":
        return None
    import ctypes
    import uuid
    from ctypes import wintypes

    class Guid(ctypes.Structure):
        _fields_ = [
            ("a", wintypes.DWORD), ("b", wintypes.WORD),
            ("c", wintypes.WORD), ("d", ctypes.c_byte * 8),
        ]

    value = uuid.UUID(folder_id)
    guid = Guid(
        value.time_low, value.time_mid, value.time_hi_version,
        (ctypes.c_byte * 8)(*value.bytes[8:]),
    )
    out = ctypes.c_wchar_p()
    try:
        if ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(out)
        ) != 0:
            return None
        return Path(out.value) if out.value else None
    except (OSError, AttributeError):
        return None
    finally:
        if out.value:
            ctypes.windll.ole32.CoTaskMemFree(out)


def videos_dir() -> Path:
    """The user's videos folder, wherever they keep it."""
    known = _known_folder(_FOLDERID_VIDEOS)
    if known is not None and known.is_dir():
        return known
    if sys.platform == "darwin":
        return Path.home() / "Movies"
    return Path.home() / "Videos"


def default_output_dir() -> Path:
    """Where a finished translation goes when the user has not said.

    Beside their other videos, in a folder that says what is in it. Inside the
    application's own data would be tidy and wrong: these are the files the
    work was done for, and they belong where the person keeps such files.
    """
    return videos_dir() / OUTPUT_FOLDER


def legacy_data_dir(root: Path | str) -> Path:
    """Where this data used to live: a `data/` folder beside the code."""
    return Path(root) / "data"


def migrate(source: Path, destination: Path) -> list[str]:
    """Carry a user's state from the old location to the new one.

    Copied, not moved, and only when the destination does not have it yet: a
    migration that goes wrong must leave the user exactly where they were.
    The old folder is left in place for the same reason, and because the
    history it describes points at job folders that are still inside it.

    Job outputs are not copied. They are named by absolute path in the
    history, so they keep working where they are, and moving gigabytes of
    finished audio into a profile folder would be a poor way to spend a first
    start.
    """
    carried: list[str] = []
    if not source.is_dir() or source.resolve() == destination.resolve():
        return carried

    destination.mkdir(parents=True, exist_ok=True)
    for name in STATE_FILES:
        old, new = source / name, destination / name
        if old.is_file() and not new.exists():
            try:
                shutil.copy2(old, new)
                carried.append(name)
            except OSError:
                # A file that cannot be copied is one the user re-enters.
                # Failing the start over it would be worse.
                continue
    return carried


def resolve_data_dir(root: Path | str, explicit: Path | str | None = None) -> Path:
    """The folder to use, migrating older state into it the first time."""
    if explicit is not None:
        return Path(explicit)
    destination = user_data_dir()
    migrate(legacy_data_dir(root), destination)
    destination.mkdir(parents=True, exist_ok=True)
    return destination
