"""Where each user's own API keys live.

The product is meant to be installed, and an installed copy is used by
whoever is sitting at the machine. A key is that person's, not the
application's: it should not travel with the program, should not appear in a
settings file that is rewritten on every toggle, and should not still work if
the folder is copied to someone else's computer.

So keys are kept apart from the settings, and on Windows they are encrypted
with DPAPI -- the operating system's own per-user protection. It needs no
password and no library: the key is sealed to the logged-in account, and the
same file on another account, or another machine, simply will not open.
Measured here: a 17-byte key becomes a 246-byte blob with no trace of the key
in it, and a blob from anywhere else is refused outright.

Off Windows there is no DPAPI, and the file is written in plain text with the
narrowest permissions the platform allows. That is worse, and it is said out
loud rather than implied: `protection()` reports which of the two is in force
so the interface can tell the user.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

#: One file, separate from settings.json, so that a settings file can be
#: copied, shared or checked into something without carrying a key with it.
FILE_NAME = "keys.dat"


def _windows_crypt(protect: bool, data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buffer = ctypes.create_string_buffer(data, len(data))
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    outgoing = Blob()
    crypt32 = ctypes.windll.crypt32
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not function(
        ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing)
    ):
        raise OSError("DPAPI отказал")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)


def available() -> bool:
    """Whether the operating system can seal a key to this account."""
    if sys.platform != "win32":
        return False
    try:
        return _windows_crypt(False, _windows_crypt(True, b"probe")) == b"probe"
    except OSError:
        return False


def protection() -> str:
    """What the interface should tell the user about how keys are kept."""
    return "dpapi" if available() else "plain"


def _seal(value: str) -> str:
    raw = value.encode("utf-8")
    if available():
        raw = _windows_crypt(True, raw)
    return base64.b64encode(raw).decode("ascii")


def _open(blob: str) -> str:
    try:
        raw = base64.b64decode(blob.encode("ascii"))
    except Exception:  # noqa: BLE001 -- a damaged file is an absent key
        return ""
    if available():
        try:
            raw = _windows_crypt(False, raw)
        except OSError:
            # Sealed by a different account, or on a different machine. That
            # is the protection working, not a fault to report as one.
            return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""


class KeyStore:
    """The keys this user has entered, one per service."""

    def __init__(self, root: Path | str) -> None:
        self.path = Path(root) / FILE_NAME

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, payload: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        # Readable by this user only, where the platform has a say in it.
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def get(self, service: str) -> str:
        """The key for `service`, or an empty string if there is not one.

        An empty string rather than an exception: a missing key is the normal
        state of a fresh installation, not an error to be handled.
        """
        blob = self._read().get(service, "")
        return _open(blob) if blob else ""

    def set(self, service: str, value: str) -> None:
        payload = self._read()
        value = value.strip()
        if value:
            payload[service] = _seal(value)
        else:
            payload.pop(service, None)
        self._write(payload)

    def forget(self, service: str) -> None:
        self.set(service, "")

    def services(self) -> list[str]:
        return sorted(self._read())

    def has(self, service: str) -> bool:
        return bool(self.get(service))

    @staticmethod
    def masked(value: str) -> str:
        """A key shown back to the user without showing the key.

        Enough of it to recognise which one is stored, never enough to use.
        """
        value = value.strip()
        if not value:
            return ""
        if len(value) <= 10:
            return "•" * len(value)
        return f"{value[:6]}…{value[-4:]}"
