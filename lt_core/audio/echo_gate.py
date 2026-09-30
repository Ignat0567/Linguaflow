"""Protection against the system translating its own voice.

The failure this prevents: the user asks for spoken translation while capturing
system audio. Piper plays the German into the speakers, WASAPI loopback records
those same speakers, the pipeline transcribes the German, translates it back,
and speaks the result -- which is captured again. Each turn is slower and more
garbled than the last, and the session degrades into noise within a minute.

There are two defences, and they are not interchangeable.

`check_routing()` is the real fix. If synthesised speech never reaches the
captured device, no loop can form, and the user can be told so before the
session starts rather than after it has gone wrong. This is a configuration
question with a configuration answer.

`EchoGate` is the fallback, for when the user insists on capturing the device
they are also listening on -- which is legitimate: one pair of headphones, a
call they want translated aloud. It suppresses captured audio for as long as
we are speaking, plus a tail for the round trip through the audio stack.

That tail is not negligible. The Day 0 spike found this machine's default
output is a Bluetooth headset, and Bluetooth adds 150-250 ms between handing
Windows a buffer and hearing it. Close the gate too early and the last syllable
of our own speech is captured and re-translated -- the loop starts from a single
word.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np

from .types import AudioChunk, DeviceInfo

# Enough for Bluetooth, which is the worst common case. Wired output needs far
# less, but the cost of being generous is only that the gate stays shut a
# little longer after we stop speaking.
DEFAULT_TAIL = 0.30


@dataclass(frozen=True)
class RoutingAdvice:
    """Whether a capture/playback pairing can feed back on itself."""

    safe: bool
    reason: str
    remedy: str | None = None


def check_routing(capture: DeviceInfo, playback_name: str | None) -> RoutingAdvice:
    """Decide whether synthesised speech can reach the captured device."""
    if capture.kind != "system":
        return RoutingAdvice(
            True, "Захват с микрофона: собственная озвучка в него не попадает "
                  "напрямую (акустическая связь через колонки возможна, но её "
                  "гасит временной затвор)."
        )
    if not playback_name:
        return RoutingAdvice(
            True, "Устройство вывода не выбрано; маршрутизация будет проверена "
                  "при запуске озвучки."
        )
    if capture.mirrors_output == playback_name:
        return RoutingAdvice(
            False,
            f"Озвучка играет в «{playback_name}», и с него же идёт захват. "
            f"Система начнёт переводить собственный перевод.",
            remedy="Выберите для озвучки другое устройство — наушники или "
                   "виртуальный кабель (VB-Audio Cable).",
        )
    return RoutingAdvice(
        True, f"Захват с «{capture.mirrors_output}», озвучка в «{playback_name}» — "
              f"пути не пересекаются."
    )


class EchoGate:
    """Suppresses captured audio while we are speaking.

    Thread-safe by design: playback runs on the TTS thread and filtering on the
    capture thread, and they touch the same deadline.
    """

    #: How long finished spans are remembered. A chunk older than this has
    #: long been looked at; the list must not grow for the length of a talk.
    MEMORY = 120.0

    def __init__(self, tail: float = DEFAULT_TAIL) -> None:
        self.tail = tail
        self._lock = threading.Lock()
        self._open_until = 0.0  # monotonic deadline; gate is shut until then
        self._speaking = False
        self._since = 0.0  # when the current line began
        #: (start, end) of every line spoken, end including the tail.
        self._spans: list[tuple[float, float]] = []
        self._muted_chunks = 0
        self._muted_seconds = 0.0

    # -- signalled by the playback side ----------------------------------
    def begin_playback(self) -> None:
        with self._lock:
            self._speaking = True
            self._since = time.monotonic()

    def end_playback(self) -> None:
        """Called when the last sample has been handed to the device."""
        with self._lock:
            now = time.monotonic()
            self._speaking = False
            self._open_until = max(self._open_until, now + self.tail)
            self._spans.append((self._since, now + self.tail))
            self._spans = [span for span in self._spans if span[1] > now - self.MEMORY]

    def extend(self, seconds: float) -> None:
        """Hold the gate shut for audio already queued but not yet played."""
        with self._lock:
            self._open_until = max(
                self._open_until, time.monotonic() + seconds + self.tail
            )

    class _Playback:
        def __init__(self, gate: "EchoGate") -> None:
            self._gate = gate

        def __enter__(self) -> "EchoGate._Playback":
            self._gate.begin_playback()
            return self

        def __exit__(self, *exc_info: object) -> None:
            self._gate.end_playback()

    def playing(self) -> "EchoGate._Playback":
        """`with gate.playing(): ...` around synthesised output."""
        return EchoGate._Playback(self)

    # -- consulted by the capture side -----------------------------------
    @property
    def is_shut(self) -> bool:
        with self._lock:
            return self._speaking or time.monotonic() < self._open_until

    def was_shut_at(self, moment: float) -> bool:
        """Whether our own voice could be in audio captured at `moment`."""
        with self._lock:
            if self._speaking and moment >= self._since:
                return True
            if self._since <= moment < self._open_until:
                return True
            return any(start <= moment <= end for start, end in self._spans)

    def filter(self, chunk: AudioChunk) -> AudioChunk:
        """Zero a chunk that arrived while we were speaking.

        The chunk is zeroed rather than dropped so that downstream timing stays
        continuous: a subtitle at 12.4 s should still land at 12.4 s, whether or
        not we were talking over it.

        Judged by when the chunk was captured. It used to be judged by when it
        was filtered, and the two are far apart: the consumer reading a line
        aloud filters nothing, then filters everything captured meanwhile
        with the gate already open. Measured on a fast speaker, 60 s with the
        voice on: of the audio captured while the voice played, 5.1 s was
        muted and 13.8 s let through, and 4.9 s captured before it began was
        muted instead.
        """
        moment = chunk.captured_at or time.monotonic()
        if not self.was_shut_at(moment):
            return chunk
        self._muted_chunks += 1
        self._muted_seconds += chunk.duration
        return AudioChunk(
            samples=np.zeros_like(chunk.samples),
            start_time=chunk.start_time,
            muted=True,
            captured_at=chunk.captured_at,
        )

    @property
    def muted_seconds(self) -> float:
        return self._muted_seconds

    @property
    def muted_chunks(self) -> int:
        return self._muted_chunks
