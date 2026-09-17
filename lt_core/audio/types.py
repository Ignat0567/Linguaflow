"""Shared audio types.

Everything downstream of capture speaks one dialect: float32 mono at 16 kHz in
[-1, 1]. Sources differ (a Bluetooth headset reports 44100, most other Windows
devices 48000, media files anything at all), so normalisation happens at the
source boundary and nowhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

TARGET_SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class AudioChunk:
    """A block of mono float32 audio at TARGET_SAMPLE_RATE."""

    samples: np.ndarray
    # Seconds since the capture session started, for the first sample in this
    # chunk. Session-relative rather than wall-clock so that subtitle timing
    # stays correct regardless of when the session began.
    start_time: float
    # True when the echo gate suppressed this chunk because our own synthesised
    # speech was playing. Carried rather than dropped so the caller can still
    # advance its clock; see lt_core.audio.echo_gate.
    muted: bool = False

    def __post_init__(self) -> None:
        if self.samples.dtype != np.float32:
            raise TypeError(f"expected float32 samples, got {self.samples.dtype}")
        if self.samples.ndim != 1:
            raise ValueError(f"expected mono, got {self.samples.ndim} dimensions")

    @property
    def duration(self) -> float:
        return len(self.samples) / TARGET_SAMPLE_RATE

    @property
    def end_time(self) -> float:
        return self.start_time + self.duration


@dataclass(frozen=True)
class DeviceInfo:
    """A capture source the user can pick in the UI.

    `backend` matters: sounddevice and PyAudioWPatch maintain separate index
    spaces, and they overlap. Index 25 is a Realtek microphone to one library
    and a Realtek loopback to the other. Carrying the backend alongside the
    index is what keeps "open device 25" unambiguous.
    """

    backend: str  # "sounddevice" | "wasapi-loopback"
    index: int
    name: str
    kind: str  # "microphone" | "system"
    sample_rate: int
    channels: int
    is_default: bool = False
    # Loopback devices mirror an output device; this is that device's name.
    # The echo gate needs it to detect the "TTS plays into the captured
    # device" feedback loop.
    mirrors_output: str | None = field(default=None)
    # Other host-API backings of this same physical device, best first, as
    # (index, sample_rate, channels). Windows keeps entries for hardware that
    # has been unplugged, and an entry that enumerates cleanly can still refuse
    # to open, so one name needs more than one way in.
    alternates: tuple[tuple[int, int, int], ...] = field(default=())

    @property
    def openings(self) -> tuple[tuple[int, int, int], ...]:
        """Every way to open this device, preferred first."""
        return ((self.index, self.sample_rate, self.channels), *self.alternates)

    @property
    def key(self) -> str:
        return f"{self.backend}:{self.index}"

    @property
    def is_low_quality(self) -> bool:
        """Below 16 kHz the device cannot carry the band the ASR model needs.

        In practice this is the Bluetooth Hands-Free Profile, which Windows
        offers at 8 kHz whenever a headset's microphone is active. It is worth
        surfacing, because the device name gives the user no hint.
        """
        return self.sample_rate < TARGET_SAMPLE_RATE

    @property
    def label(self) -> str:
        tag = "Система" if self.kind == "system" else "Микрофон"
        star = " ★" if self.is_default else ""
        warn = f"  ⚠ {self.sample_rate} Гц" if self.is_low_quality else ""
        return f"[{tag}] {self.name}{star}{warn}"
