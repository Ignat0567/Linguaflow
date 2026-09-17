"""Streaming voice activity detection.

Reuses the Silero v6 model that ships inside faster-whisper, so there is no
extra dependency and no second download. What faster-whisper exposes is a batch
API: `get_speech_timestamps()` takes a complete recording, and `SileroVADModel`
zeroes its LSTM state on every call. Feeding that a chunk at a time would make
each chunk look like the start of a new recording, which reads breath and room
tone as speech onsets.

`StreamingVad` keeps the recurrent state and the 64-sample lookback context
across calls, so a continuous capture is scored as one continuous signal.

Why this matters beyond saving GPU cycles: the Day 0 spike showed that with
fixed 5-second windows the transcriber emitted a nonexistent German word,
`Abdeckungsreaktionslatenz`, because a window boundary fell mid-phrase. Speech
boundaries have to come from the audio, not from a timer.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .types import TARGET_SAMPLE_RATE

# Silero v6 at 16 kHz consumes exactly 512 samples (32 ms) per step, plus 64
# samples of preceding context.
FRAME_SAMPLES = 512
CONTEXT_SAMPLES = 64
FRAME_DURATION = FRAME_SAMPLES / TARGET_SAMPLE_RATE


@dataclass(frozen=True)
class SpeechEvent:
    """A transition between speech and silence, timed in session seconds."""

    kind: str  # "speech_start" | "speech_end"
    time: float


class StreamingVad:
    """Per-frame speech probability over a continuous stream."""

    def __init__(self) -> None:
        import onnxruntime
        from faster_whisper.utils import get_assets_path

        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.log_severity_level = 4
        self._session = onnxruntime.InferenceSession(
            f"{get_assets_path()}/silero_vad_v6.onnx",
            providers=["CPUExecutionProvider"],
            sess_options=options,
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT_SAMPLES, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self._frames_seen = 0

    @property
    def time(self) -> float:
        """Seconds of audio consumed so far."""
        return self._frames_seen * FRAME_DURATION

    def push(self, samples: np.ndarray) -> list[float]:
        """Feed audio of any length; get one probability per complete frame.

        The model takes a whole sequence of frames per call, so every frame
        buffered by this call goes in together. One-frame-per-call works but
        pays the ONNX dispatch cost for each 32 ms of audio.
        """
        self._pending = np.concatenate([self._pending, np.asarray(samples, np.float32)])

        count = self._pending.size // FRAME_SAMPLES
        if count == 0:
            return []

        used = count * FRAME_SAMPLES
        frames = self._pending[:used].reshape(count, FRAME_SAMPLES)
        self._pending = self._pending[used:]

        # Each frame is preceded by the tail of the frame before it; the first
        # one continues from wherever the previous call left off.
        contexts = np.empty((count, CONTEXT_SAMPLES), dtype=np.float32)
        contexts[0] = self._context
        if count > 1:
            contexts[1:] = frames[:-1, -CONTEXT_SAMPLES:]
        self._context = frames[-1, -CONTEXT_SAMPLES:].copy()

        batch = np.concatenate([contexts, frames], axis=1)
        probabilities, self._h, self._c = self._session.run(
            None, {"input": batch, "h": self._h, "c": self._c}
        )
        self._frames_seen += count
        return [float(p) for p in np.asarray(probabilities).reshape(-1)]


class SpeechSegmenter:
    """Turns frame probabilities into speech/silence transitions.

    Hysteresis rather than a single threshold: crossing `threshold` starts
    speech, but it only ends after `min_silence` continuously below
    `neg_threshold`. A single threshold would chop every natural pause between
    words into a separate segment.

    Reported boundaries are padded outward by `speech_pad`, because Silero
    marks the onset of voicing and clips the unvoiced consonant in front of it
    (the /s/ in "start"), which the transcriber then has to guess at.

    A start is withheld until `min_speech` of it exists, so a cough or a
    keystroke never reaches the caller. Publishing immediately and retracting
    later cannot work: by then the start may have been emitted in an earlier
    call and already acted upon.
    """

    def __init__(
        self,
        threshold: float = 0.5,
        neg_threshold: float | None = None,
        min_silence: float = 0.5,
        min_speech: float = 0.10,
        speech_pad: float = 0.20,
    ) -> None:
        self.threshold = threshold
        self.neg_threshold = (
            neg_threshold if neg_threshold is not None else max(threshold - 0.15, 0.01)
        )
        self.min_silence = min_silence
        self.min_speech = min_speech
        self.speech_pad = speech_pad
        self.reset()

    def reset(self) -> None:
        self._in_speech = False
        self._announced = False
        self._speech_started_at = 0.0
        self._silence_started_at: float | None = None
        self._frames = 0

    @property
    def in_speech(self) -> bool:
        """True once a start has been published, not merely suspected."""
        return self._in_speech and self._announced

    def push(self, probabilities: list[float]) -> list[SpeechEvent]:
        events: list[SpeechEvent] = []
        for probability in probabilities:
            now = self._frames * FRAME_DURATION
            self._frames += 1

            if not self._in_speech:
                if probability >= self.threshold:
                    self._in_speech = True
                    self._announced = False
                    self._speech_started_at = now
                    self._silence_started_at = None
                continue

            if probability >= self.neg_threshold:
                self._silence_started_at = None
                if not self._announced and now - self._speech_started_at >= self.min_speech:
                    self._announced = True
                    events.append(
                        SpeechEvent(
                            "speech_start",
                            max(0.0, self._speech_started_at - self.speech_pad),
                        )
                    )
                continue

            if self._silence_started_at is None:
                self._silence_started_at = now
            elif now - self._silence_started_at >= self.min_silence:
                end = self._silence_started_at
                if self._announced:
                    events.append(SpeechEvent("speech_end", end + self.speech_pad))
                # Otherwise the burst never reached min_speech -- a cough, a
                # door, a keystroke -- and no one was ever told about it.
                self._in_speech = False
                self._announced = False
                self._silence_started_at = None
        return events

    def flush(self) -> list[SpeechEvent]:
        """Close an open segment at end of stream."""
        if not (self._in_speech and self._announced):
            self._in_speech = False
            self._announced = False
            return []
        self._in_speech = False
        self._announced = False
        return [SpeechEvent("speech_end", self._frames * FRAME_DURATION)]
