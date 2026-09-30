# -*- mode: python ; coding: utf-8 -*-
"""One-folder build of the window.

Models are not collected here. They are gigabytes and already live in
`models/`; the build script copies them next to the executable afterwards.
Libraries, including the CUDA DLLs, are collected into `_internal`.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent

PACKAGES = (
    "PySide6",
    "faster_whisper",
    "ctranslate2",
    "transformers",
    "sentencepiece",
    "tokenizers",
    "huggingface_hub",
    "piper",
    "pyopenjtalk",
    "sherpa_onnx",
    "onnxruntime",
    "sounddevice",
    "numpy",
    "av",
    "imageio_ffmpeg",
    "yt_dlp",
    "yt_dlp_ejs",
    "deno",
    "adblock",
    "certifi",
)

datas = []
binaries = []
hidden = [
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "lt_core",
    "lt_ui",
]


def _take(package: str) -> None:
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception:
        return
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hidden.extend(package_hidden)


for name in PACKAGES:
    _take(name)


def _nvidia_dlls() -> list[tuple[str, str]]:
    """The same tree `_nvidia_roots` looks for inside a frozen program."""
    nvidia = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    found = []
    if not nvidia.is_dir():
        return found
    for dll in nvidia.rglob("*.dll"):
        dest = Path("nvidia") / dll.relative_to(nvidia).parent
        found.append((str(dll), dest.as_posix()))
    return found


binaries.extend(_nvidia_dlls())

a = Analysis(
    [str(ROOT / "tools" / "app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "tensorflow", "tkinter", "pytest", "IPython", "matplotlib", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Linguaflow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Linguaflow",
)
