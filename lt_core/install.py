"""Where the program itself lives, as opposed to a user's own files.

A checkout is the repository. An installed copy is the folder of the
executable: libraries sit in PyInstaller's `_internal`, and the models sit
beside the executable. They are gigabytes, identical for every user and
read-only in use, so they belong with the installation and not inside the
archive that would be unpacked on every launch, and not in a profile.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_VERSION = "0.9.0"


def install_root() -> Path:
    """The folder that holds the program, its assets and its models."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def model_root() -> Path:
    return install_root() / "models"
