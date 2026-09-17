"""Windows microphone permission.

Windows 11 gates microphone access behind a privacy setting, and denies it in
the worst possible way: the devices still enumerate. They appear in the picker
with the right names and sample rates, `check_input_settings` approves them,
and only the attempt to open one fails -- with "Invalid device [PaErrorCode
-9996]", or a DirectSound error, or an MME error, depending on which host API
happens to be tried first.

Nothing in that mentions permission. On the Day 1 machine every one of ten
microphones failed this way while system-audio loopback kept working perfectly,
because the setting covers capture endpoints and not render endpoints. Anyone
meeting this without an explanation concludes the program is broken.

So the permission is read directly and reported as what it is. Reading only --
the toggle belongs to the user, and an audio tool has no business changing a
system privacy setting on their behalf.
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
    if desktop is None:
        # Not "denied" so much as never granted. Observed on the Day 1 machine:
        # the master toggle reads Allow, this value is absent, and every one of
        # ten microphones fails to open in two independent PortAudio builds
        # while loopback keeps working. Worth reporting, but not as a verdict --
        # the same absence can mean the setting was simply never touched.
        return MicrophonePermission(
            False,
            "Разрешение на микрофон для классических приложений не выдано "
            "(Windows не хранит для него значения). Обычно это и есть причина, "
            "когда устройства видны, но ни одно не открывается.",
            remedy=f"Проверьте: {setting}. Если оно уже включено, микрофон "
                   f"держит другая программа в монопольном режиме.",
        )

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
        f"Не удалось открыть «{device_name}». Устройство числится в системе, "
        f"но не отвечает — обычно это значит, что оно отключено или занято "
        f"другой программой."
    )
