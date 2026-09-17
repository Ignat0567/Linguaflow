"""Linguaflow desktop app.

    python tools/app.py
    python tools/app.py --screenshot
"""

from __future__ import annotations

import argparse
import sys
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


if __name__ == "__main__":
    raise SystemExit(main())
