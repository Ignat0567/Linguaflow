"""DirectShow microphone capture, via the bundled ffmpeg.

PortAudio cannot open a single capture device on the Day 1 machine. Ten
microphones, two independent PortAudio builds (sounddevice and PyAudioWPatch),
a process detached from the session entirely -- every attempt fails with
"Invalid device [PaErrorCode -9996]" or a generic host error. Loopback capture
through the same library works perfectly, and so does playback.

That combination pointed at a Windows privacy setting, and it was wrong. The
setting is on; ffmpeg opens the very same microphone through DirectShow and
records real audio from it on the first try. The fault is PortAudio's capture
path on this machine, not the hardware, not Windows, and not permission.

Hence a second backend. ffmpeg is already a dependency for decoding media, it
resamples to our target format in the same pass, and DirectShow is a different
road into the audio stack than WASAPI. When one road is closed the other is
usually open, which is the entire argument for having two.

Device identity here is a name, not an index, and friendly names are not
unique: two identical headsets produce two identical strings. Every device also
carries an "alternative name" -- a moniker with a GUID in it -- and that is what
gets passed to ffmpeg.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_LINE = re.compile(r'^\[dshow @ [^\]]*\]\s*(.*)$')
_DEVICE = re.compile(r'^"(?P<name>.*)"\s+\((?P<kind>audio|video)\)$')
_ALTERNATIVE = re.compile(r'^Alternative name\s+"(?P<moniker>.*)"$')

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class DshowDevice:
    name: str
    moniker: str

    @property
    def spec(self) -> str:
        """What to hand ffmpeg after `-i`.

        The moniker is unique; the friendly name is not. Falling back to the
        name when a moniker is missing is better than refusing to open at all.
        """
        return f"audio={self.moniker or self.name}"


def ffmpeg_path() -> str:
    import imageio_ffmpeg

    # Store-Python virtualises paths given to subprocesses; resolve first.
    return str(Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve())


def list_audio_devices(timeout: float = 20.0) -> list[DshowDevice]:
    """Enumerate DirectShow audio inputs.

    ffmpeg writes the list to stderr and then exits non-zero, because listing
    devices is implemented as "fail to open a device called dummy". A non-zero
    return code here is normal and says nothing about the list.
    """
    try:
        completed = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-list_devices", "true",
             "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    devices: list[DshowDevice] = []
    pending: str | None = None
    for raw in completed.stderr.splitlines():
        matched = _LINE.match(raw)
        if not matched:
            continue
        body = matched.group(1).strip()

        device = _DEVICE.match(body)
        if device:
            pending = device.group("name") if device.group("kind") == "audio" else None
            continue

        alternative = _ALTERNATIVE.match(body)
        if alternative and pending is not None:
            devices.append(DshowDevice(pending, alternative.group("moniker")))
            pending = None
    return devices


def open_stream(device: DshowDevice, sample_rate: int) -> subprocess.Popen:
    """Start ffmpeg streaming this device as mono s16le on stdout.

    ffmpeg does the downmix and resampling, so the block that arrives is
    already in the format the rest of the pipeline expects.
    """
    command = [
        ffmpeg_path(), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "dshow",
        # Keep the driver's own buffering small; the default adds latency that
        # a live translation cannot spare.
        "-audio_buffer_size", "50",
        "-i", device.spec,
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ac", "1", "-ar", str(sample_rate), "-",
    ]
    return subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=_NO_WINDOW,
    )
