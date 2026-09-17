"""Windows microphone permission.

Windows 11 gates microphone access behind a privacy setting, and denies it in
the worst possible way: the devices still enumerate. They appear in the picker
with the right names and sample rates, `check_input_settings` approves them,
and only the attempt to open one fails -- with "Invalid device [PaErrorCode
-9996]", or a DirectSound error, or an MME error, depending on which host API
happens to be tried first.

Nothing in that mentions permission, so the setting is read directly.

Read narrowly, though, and only an explicit Deny is treated as one. The first
version of this module inferred denial from a *missing* consent value, which
looked convincing -- the value was absent and all ten microphones were failing.
It was wrong. The setting was enabled the whole time; the failure was
PortAudio's capture path, and ffmpeg opened the same microphone immediately.
An absent value means the toggle was never written, which is the normal state
on a machine where nobody has touched it.

Reading only, either way: the toggle belongs to the user, and an audio tool has
no business changing a system privacy setting on their behalf.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

# Where Windows records consent. The NonPackaged subkey is the one that governs
# ordinary desktop programs; the parent key governs Store apps, and the two are
# separate toggles in the Settings UI.
_CONSENT_PATH = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
    r"\ConsentStore\microphone"
)

SETTINGS_URI = "ms-settings:privacy-microphone"


@dataclass(frozen=True)
class MicrophonePermission:
    allowed: bool
    reason: str
    remedy: str | None = None


def _read_value(root, subkey: str) -> str | None:
    import winreg

    try:
        with winreg.OpenKey(root, subkey) as key:
            value, _ = winreg.QueryValueEx(key, "Value")
            return str(value)
    except OSError:
        return None


def check_microphone_permission() -> MicrophonePermission:
    """Report whether desktop programs may open a microphone.

    Unknown states are treated as allowed: a missing key on some Windows build
    must not produce a warning that sends the user hunting for a setting that
    is already correct.
    """
    if sys.platform != "win32":
        return MicrophonePermission(True, "Проверка разрешений нужна только в Windows.")

    import winreg

    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        if _read_value(root, _CONSENT_PATH) == "Deny":
            return MicrophonePermission(
                False,
                "Доступ к микрофону запрещён в параметрах конфиденциальности Windows.",
                remedy="Параметры → Конфиденциальность и защита → Микрофон → "
                       "включите «Доступ к микрофону».",
            )

    setting = (
        "Параметры → Конфиденциальность и защита → Микрофон → «Разрешить "
        "классическим приложениям доступ к микрофону»"
    )
    desktop = _read_value(winreg.HKEY_LOCAL_MACHINE, _CONSENT_PATH + r"\NonPackaged")
    if desktop == "Deny":
        return MicrophonePermission(
            False,
            "Классическим приложениям запрещён доступ к микрофону. Устройства "
            "при этом видны в списке и выглядят исправными — Windows скрывает "
            "запрет за ошибкой драйвера.",
            remedy=f"{setting} — включите.",
        )
    # An absent value means the toggle was never written, not that it is off.
    # Reading it as denial produced a confident, wrong diagnosis: the setting
    # was on the whole time, and every microphone still refused to open --
    # because PortAudio was the thing failing, not permission. Only an explicit
    # Deny is evidence of anything.
    return MicrophonePermission(True, "Доступ к микрофону разрешён.")


def explain_open_failure(device_name: str) -> str:
    """The message for a microphone that would not open.

    Checks permission first, because that is both the likeliest cause and the
    one the user can actually fix.
    """
    permission = check_microphone_permission()
    if not permission.allowed:
        return f"{permission.reason} {permission.remedy or ''}".strip()
    return (
        f"Не удалось открыть «{device_name}» через PortAudio. Попробуйте то же "
        f"устройство с пометкой DirectShow — на части систем работает только "
        f"этот путь. Если и он молчит, устройство занято другой программой."
    )
