"""Process bootstrap.

Windows needs three things arranged before anything else is imported, each of
which was found the hard way during the Day 0 spike (docs/DAY0_SPIKE.md):

1. The CUDA/cuDNN DLLs ship inside the virtualenv, where the Windows loader will
   not look for them. CTranslate2 reports "no CUDA device" rather than a missing
   DLL, so this failure is easy to misdiagnose as a driver problem.
2. huggingface_hub downloads via symlinks, which Windows forbids without
   Developer Mode. Every end user hits this, not just developers.
3. The console here is cp1251 and raises UnicodeEncodeError on German umlauts,
   let alone Chinese or Japanese.

`bootstrap()` is idempotent and must run before importing ctranslate2 or
faster_whisper.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_done = False


def _nvidia_roots() -> list[Path]:
    """Where the pip CUDA wheels put their DLLs, in a venv and in a build.

    A checkout finds them under site-packages. A frozen program has no
    site-packages: the installer lays the same tree inside the bundle, and
    the Windows loader will not search there on its own.
    """
    roots = [Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"]
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        roots.append(Path(bundled) / "nvidia")
    return roots


def _add_cuda_dll_dirs() -> list[str]:
    """Make the bundled CUDA libraries visible to the Windows loader."""
    if sys.platform != "win32":
        return []
    # Store-Python virtualises paths handed to the DLL loader, so resolve()
    # before use.
    added = []
    for nvidia in _nvidia_roots():
        if not nvidia.is_dir():
            continue
        for bindir in sorted(nvidia.glob("*/bin")):
            try:
                os.add_dll_directory(str(bindir.resolve()))
            except OSError:
                continue
            added.append(bindir.parent.name)
    return added


def _force_utf8() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr):
        # Under pythonw.exe (the packaged GUI app) these are None.
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def bootstrap(model_root: Path | str | None = None) -> None:
    global _done
    if _done:
        return

    _force_utf8()
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if model_root is not None:
        os.environ.setdefault("HF_HOME", str(Path(model_root).resolve()))
    _add_cuda_dll_dirs()

    _done = True
