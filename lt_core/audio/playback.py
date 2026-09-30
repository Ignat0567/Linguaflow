"""Play a downloaded video's soundtrack ourselves, and keep time for its picture.

Why not QtMultimedia: on the development machine its audio output never
starts -- a QMediaPlayer with any QAudioOutput sat at position 0 on every
device, with both media backends, on a synthetic H.264 file as well as a real
one, while the same player without audio ran in real time. A PortAudio
stream, which is how Linguaflow already reads translations aloud, works.

So the sound is decoded by ffmpeg and played here, and this playback is the
clock: the picture is nudged to it, not the other way round. Ears notice a
jump in sound; eyes forgive a dropped frame.

What is played is also handed to `on_audio` before the volume is applied, so
lowering the video under a translation being read out changes what the
viewer hears and not what the recogniser does.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np


class FilePlayback:
    """A decoded soundtrack on a PortAudio output stream.

    `frames` is int16, shape (n, channels). `stream_factory` builds the output
    stream; it defaults to sounddevice and is replaced in tests, which drive
    `_callback` by hand.
    """

    #: Seconds a change of volume takes. The file dub's fade (DUCK_FADE).
    FADE = 0.15

    def __init__(
        self,
        frames: np.ndarray,
        rate: int,
        on_audio: Callable[[np.ndarray, int], None] | None = None,
        stream_factory=None,
    ) -> None:
        frames = np.asarray(frames)
        if frames.ndim == 1:
            frames = frames.reshape(-1, 1)
        self.frames = frames
        self.rate = int(rate)
        self.channels = frames.shape[1]
        self.on_audio = on_audio
        self._factory = stream_factory or _sounddevice_stream
        self._lock = threading.Lock()
        self._position = 0
        self._gain = 1.0
        self._target = 1.0
        self._stream = None
        self._playing = False
        self.finished = threading.Event()

    # -- the clock ---------------------------------------------------------
    @property
    def duration(self) -> float:
        return len(self.frames) / self.rate

    @property
    def position(self) -> float:
        """Seconds of the soundtrack played so far."""
        with self._lock:
            return self._position / self.rate

    @property
    def playing(self) -> bool:
        return self._playing

    # -- transport ---------------------------------------------------------
    def play(self) -> None:
        if self._playing:
            return
        if self._stream is None:
            self._stream = self._factory(self.rate, self.channels, self._callback)
        self.finished.clear()
        self._playing = True
        self._stream.start()

    def pause(self) -> None:
        if not self._playing:
            return
        self._playing = False
        if self._stream is not None:
            self._stream.stop()

    def seek(self, seconds: float) -> None:
        with self._lock:
            self._position = int(max(0.0, min(seconds, self.duration)) * self.rate)

    def close(self) -> None:
        self.pause()
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    # -- volume ------------------------------------------------------------
    @property
    def volume(self) -> float:
        return self._target

    def set_volume(self, level: float) -> None:
        """Move to `level` over FADE seconds, from wherever it is now."""
        self._target = float(max(0.0, min(1.0, level)))

    # -- the audio thread ----------------------------------------------------
    def _callback(self, outdata, frame_count, _time=None, _status=None) -> None:
        with self._lock:
            start = self._position
            chunk = self.frames[start:start + frame_count]
            self._position = start + len(chunk)
        got = len(chunk)
        if got:
            samples = chunk.astype(np.float32) / 32768.0
            if self.on_audio is not None:
                self.on_audio(samples.mean(axis=1), self.rate)
            outdata[:got] = samples * self._ramp(got)[:, None]
        if got < frame_count:
            outdata[got:] = 0
            self._playing = False
            self.finished.set()

    def _ramp(self, n: int) -> np.ndarray:
        """Per-frame gain for this block, stepping towards the target."""
        start, target = self._gain, self._target
        if start == target:
            return np.full(n, start, dtype=np.float32)
        step = n / (self.FADE * self.rate)
        end = target if abs(target - start) <= step else start + step * np.sign(target - start)
        self._gain = float(end)
        return np.linspace(start, end, n, dtype=np.float32)


def _sounddevice_stream(rate: int, channels: int, callback):
    import sounddevice as sd

    return sd.OutputStream(
        samplerate=rate, channels=channels, dtype="float32", callback=callback,
    )
