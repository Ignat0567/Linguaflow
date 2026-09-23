"""Linguaflow desktop app.

    python tools/app.py
    python tools/app.py --screenshot
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lt_ui.window import run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="linguaflow", description="Linguaflow")
    parser.add_argument(
        "--screenshot",
        nargs="?",
        const="spike",
        metavar="DIR",
        help="сохранить снимки пяти экранов и выйти",
    )
    parser.add_argument("--data", help="папка для настроек и истории")
    args = parser.parse_args()
    return run(data_dir=args.data, screenshot=args.screenshot)


def _remember_crash() -> None:
    """A windowed build has no console. Leave the traceback where it can be found."""
    if not getattr(sys, "frozen", False):
        return
    folder = Path(os.environ.get("APPDATA") or Path.home()) / "Linguaflow"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "startup.log").write_text(traceback.format_exc(), encoding="utf-8")
    except OSError:
        pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        _remember_crash()
        raise
