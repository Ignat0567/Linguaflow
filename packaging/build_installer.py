"""Build the Windows installer.

    .venv\\Scripts\\python.exe packaging\\build_installer.py

PyInstaller writes dist\\Linguaflow. Models and the two images are copied
beside the executable — they are the installation, not the library archive.
Inno Setup then packs that folder. The setup file lands in
packaging\\output\\Linguaflow-setup.exe.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DIST = ROOT / "dist" / "Linguaflow"
SPEC = Path(__file__).resolve().parent / "linguaflow.spec"
ISS = Path(__file__).resolve().parent / "linguaflow.iss"

#: What of models/ an installed copy needs. The hub cache's download
#: scratch (xet) is not a model.
MODEL_PARTS = ("hub", "piper", "speaker")


def _python() -> Path:
    return Path(sys.executable)


def _pyinstaller() -> None:
    subprocess.run(
        [_python(), "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)],
        cwd=ROOT,
        check=True,
    )


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _stage_payload() -> None:
    if not DIST.is_dir():
        raise SystemExit(f"PyInstaller did not write {DIST}")
    models = ROOT / "models"
    for part in MODEL_PARTS:
        source = models / part
        if not source.is_dir():
            raise SystemExit(f"missing {source}")
        print(f"copying {source} ...", flush=True)
        _copy_tree(source, DIST / "models" / part)
    assets = ROOT / "assets"
    if not assets.is_dir():
        raise SystemExit(f"missing {assets}")
    _copy_tree(assets, DIST / "assets")


def _iscc() -> Path:
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(os.environ.get("INNO_SETUP", "")),
        Path(local) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    raise SystemExit(
        "Inno Setup 6 is not installed (ISCC.exe). "
        "Install it, then run this script again."
    )


def _compile() -> None:
    from lt_core.install import APP_VERSION

    output = ISS.parent / "output"
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(_iscc()),
            f"/DAppVersion={APP_VERSION}",
            str(ISS),
        ],
        cwd=ISS.parent,
        check=True,
    )
    setup = output / "Linguaflow-setup.exe"
    if not setup.is_file():
        raise SystemExit(f"installer was not written: {setup}")
    parts = sorted(output.glob("Linguaflow-setup*.bin"))
    total = setup.stat().st_size + sum(part.stat().st_size for part in parts)
    names = ", ".join(part.name for part in parts)
    extra = f" + {names}" if names else ""
    print(f"installer: {setup}{extra} ({total / 1e9:.2f} GB)", flush=True)


def main() -> int:
    os.chdir(ROOT)
    _pyinstaller()
    _stage_payload()
    _compile()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
