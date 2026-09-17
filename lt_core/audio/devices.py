"""Capture device discovery.

Microphones come from sounddevice; system audio ("what you hear") comes from
WASAPI loopback via PyAudioWPatch, which exposes one loopback device per output
device. Both are presented as one list so the UI has a single picker.

Windows reports the same physical microphone once per host API, at a different
sample rate each time. The Day 1 machine showed one webcam mic four times at
44100 / 44100 / 48000 / 32000 Hz. Offering all four to the user is a trap: the
names are identical, so the choice is effectively random. We keep one entry per
physical device and pick the best backing for it.
"""

from __future__ import annotations

import re

from .types import DeviceInfo

_LOOPBACK_SUFFIX = " [Loopback]"


def _clean_name(name: str) -> str:
    r"""Tidy raw Windows device names for display.

    Some drivers report an unexpanded resource reference instead of a name, e.g.
    `Kopfhoerer (@System32\drivers\bthhfenum.sys,#2;%1 Hands-Free%0\n;(SoundCore 2))`
    -- embedded newline included. Left alone it breaks the picker layout and
    tells the user nothing. Rendered as "Kopfhoerer (SoundCore 2, Hands-Free)"
    it also explains why that entry sounds bad.
    """
    name = re.sub(r"\s+", " ", name).strip()
    match = re.match(r"^([^(]+)\(@[^)]*?%1\s*([^%]+)%0\s*;?\(?([^)]*)\)?\)$", name)
    if match:
        prefix, profile, device = (part.strip() for part in match.groups())
        return f"{prefix} ({device}, {profile})" if device else f"{prefix} ({profile})"
    return name

# Lower is better. WASAPI is the native Windows path: lowest latency and no
# resampling in the driver stack. MME is the legacy fallback with the worst
# latency. WDM-KS bypasses the mixer and often refuses to open at all.
_HOST_API_RANK = {
    "Windows WASAPI": 0,
    "Windows DirectSound": 1,
    "MME": 2,
    "Windows WDM-KS": 3,
}


def _rank(host_api: str, sample_rate: int) -> tuple[int, int]:
    # Prefer the better API, then the higher sample rate. The Bluetooth headset
    # exposes WASAPI at 8 kHz (Hands-Free Profile) while DirectSound reports
    # 44100, so rate has to be part of the comparison, not just the API.
    quality_tier = 0 if sample_rate >= 16_000 else 1
    return (quality_tier, _HOST_API_RANK.get(host_api, 9) * 1000 - sample_rate // 1000)


def list_microphones() -> list[DeviceInfo]:
    import sounddevice as sd

    host_apis = sd.query_hostapis()
    try:
        default_in = sd.default.device[0]
    except (AttributeError, IndexError, TypeError):
        default_in = None

    # Gather every backing of every name first; choosing among them, and
    # keeping the rest as fallbacks, is a second step.
    candidates: dict[str, list[tuple[tuple[int, int], int, int, int, bool]]] = {}
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        api = host_apis[dev["hostapi"]]["name"]
        rate = int(dev["default_samplerate"])
        channels = int(dev["max_input_channels"])
        name = _clean_name(dev["name"])
        candidates.setdefault(name, []).append(
            (_rank(api, rate), idx, rate, channels, idx == default_in)
        )

    devices: list[DeviceInfo] = []
    for name, entries in candidates.items():
        entries.sort(key=lambda entry: entry[0])
        _, idx, rate, channels, _ = entries[0]
        devices.append(
            DeviceInfo(
                backend="sounddevice",
                index=idx,
                name=name,
                kind="microphone",
                sample_rate=rate,
                channels=channels,
                # The default marker belongs to the physical device, not to
                # whichever host API happened to rank highest.
                is_default=any(entry[4] for entry in entries),
                alternates=tuple(
                    (entry[1], entry[2], entry[3]) for entry in entries[1:]
                ),
            )
        )
    return devices


def list_system_outputs() -> list[DeviceInfo]:
    """WASAPI loopback devices, one per output device."""
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        return []

    pa = pyaudio.PyAudio()
    try:
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            return []
        default_output = pa.get_device_info_by_index(
            wasapi["defaultOutputDevice"]
        )["name"]

        found: list[DeviceInfo] = []
        seen: set[str] = set()
        for dev in pa.get_loopback_device_info_generator():
            mirrored = _clean_name(dev["name"].removesuffix(_LOOPBACK_SUFFIX))
            # A multi-monitor HDMI output appears twice under the same name;
            # only the first is routed.
            if mirrored in seen:
                continue
            seen.add(mirrored)
            found.append(
                DeviceInfo(
                    backend="wasapi-loopback",
                    index=int(dev["index"]),
                    name=mirrored,
                    kind="system",
                    sample_rate=int(dev["defaultSampleRate"]),
                    channels=int(dev["maxInputChannels"]),
                    is_default=(mirrored == default_output),
                    mirrors_output=mirrored,
                )
            )
        return found
    finally:
        pa.terminate()


def list_capture_devices() -> list[DeviceInfo]:
    """Everything the user can capture from: defaults first, then by name."""
    devices = list_microphones() + list_system_outputs()
    return sorted(
        devices,
        key=lambda d: (not d.is_default, d.is_low_quality, d.kind, d.name.lower()),
    )


def default_device(kind: str) -> DeviceInfo | None:
    candidates = [d for d in list_capture_devices() if d.kind == kind]
    if not candidates:
        return None
    return next((d for d in candidates if d.is_default), candidates[0])


def find_device(key: str) -> DeviceInfo | None:
    """Resolve a saved "backend:index" key back to a live device."""
    return next((d for d in list_capture_devices() if d.key == key), None)
