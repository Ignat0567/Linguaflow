"""Sample-rate and channel conversion.

Uses soxr (VHQ band-limited) rather than index picking. The Day 0 spike
resampled 48k->16k by selecting nearest indices, which aliases: energy above
8 kHz folds back into the speech band as broadband noise. It survived the
benchmark because synthesised speech is spectrally clean, but it would have
cost real accuracy on real microphones.
"""

from __future__ import annotations

import numpy as np
import soxr

from .types import TARGET_SAMPLE_RATE


def to_mono(samples: np.ndarray, channels: int) -> np.ndarray:
    """Downmix interleaved frames to mono by averaging channels."""
    if channels == 1:
        return samples.reshape(-1)
    usable = (len(samples) // channels) * channels
    return samples[:usable].reshape(-1, channels).mean(axis=1)


def pcm16_to_float32(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


class StreamResampler:
    """Stateful resampler for continuous capture.

    A fresh resampler per block would ring at every block boundary, producing a
    faint periodic click at the block rate. soxr's stream mode carries filter
    state across calls instead.
    """

    def __init__(self, source_rate: int, channels: int,
                 target_rate: int = TARGET_SAMPLE_RATE) -> None:
        self.source_rate = source_rate
        self.channels = channels
        self.target_rate = target_rate
        self._passthrough = source_rate == target_rate
        self._stream = None if self._passthrough else soxr.ResampleStream(
            source_rate, target_rate, 1, dtype="float32", quality="VHQ"
        )

    def process(self, samples: np.ndarray, last: bool = False) -> np.ndarray:
        mono = to_mono(np.asarray(samples, dtype=np.float32), self.channels)
        if self._passthrough:
            return mono
        return self._stream.resample_chunk(mono, last=last).astype(np.float32, copy=False)

    def flush(self) -> np.ndarray:
        """Release audio still inside the filter at end of stream.

        soxr emits in bursts, holding back roughly a filter length. Without
        this the tail never comes out: 50 ms at 22.05 kHz, which is the last
        syllable of a recording arriving truncated or not at all.
        """
        if self._passthrough:
            return np.zeros(0, dtype=np.float32)
        return self._stream.resample_chunk(
            np.zeros(0, dtype=np.float32), last=True
        ).astype(np.float32, copy=False)
