"""How high a voice is, so the dub can answer in kind.

A dub that reads a man's line in a woman's voice is wrong in a way subtitles
never are: the listener hears two people where there is one, and stops
trusting who said what. To match them, something has to decide which voice a
speaker has, and the cheapest honest signal is the fundamental frequency --
the rate the vocal folds vibrate at.

This is not speaker recognition and does not pretend to be. It answers one
question, per stretch of speech: is this voice low or high? The threshold and
what it costs when it is wrong are measured in `docs/DAY7.md`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: The range a human speaking voice lives in. Below 60 Hz is a rumble, above
#: 400 Hz is a shout or a child, and both ends of the search window are where
#: octave errors come from -- halve or double a real pitch and it still looks
#: like a peak.
MIN_F0, MAX_F0 = 60.0, 400.0

#: Frame long enough to hold two periods of the lowest pitch searched for.
#: At 60 Hz one period is 16.7 ms, so 40 ms is the floor for a correlation
#: that can see a repeat at all.
FRAME_SECONDS = 0.040
HOP_SECONDS = 0.010

#: How strongly a frame has to repeat itself to count as voiced. Unvoiced
#: speech -- s, f, sh -- has no periodicity and would otherwise contribute
#: whatever the noise floor happened to peak at.
VOICED_CORRELATION = 0.30
#: Frames quieter than this are silence between words.
SILENCE_RMS = 0.012


@dataclass(frozen=True)
class Pitch:
    """What was measured over one stretch of audio."""

    #: Median fundamental frequency over voiced frames, in Hz. 0.0 when
    #: nothing voiced was found.
    median: float
    #: Fraction of frames that were voiced at all. A cue of applause or
    #: music scores near zero, and its pitch should not be believed.
    voiced: float
    #: How many voiced frames the median rests on.
    frames: int

    @property
    def confident(self) -> bool:
        """Whether there is enough voiced speech here to classify.

        Both tests matter. A quarter-second of speech in a five-second cue is
        a cough, and 12 frames is 120 ms -- about one syllable, which is the
        least a median can be built from.
        """
        return self.median > 0.0 and self.voiced >= 0.20 and self.frames >= 12


def estimate(samples: np.ndarray, rate: int) -> Pitch:
    """Measure the pitch of one stretch of speech."""
    if samples.size == 0 or rate <= 0:
        return Pitch(0.0, 0.0, 0)

    audio = np.asarray(samples, dtype=np.float32)
    frame = int(FRAME_SECONDS * rate)
    hop = max(1, int(HOP_SECONDS * rate))
    if audio.size < frame:
        return Pitch(0.0, 0.0, 0)

    lowest = max(1, int(rate / MAX_F0))
    highest = min(frame - 1, int(rate / MIN_F0))
    if highest <= lowest:
        return Pitch(0.0, 0.0, 0)

    window = np.hanning(frame).astype(np.float32)
    starts = range(0, audio.size - frame + 1, hop)
    total = 0
    found: list[float] = []

    for start in starts:
        total += 1
        block = audio[start:start + frame]
        if float(np.sqrt(np.mean(block * block))) < SILENCE_RMS:
            continue

        block = (block - block.mean()) * window
        energy = float(np.dot(block, block))
        if energy <= 0.0:
            continue

        # Autocorrelation through the frequency domain: padding to twice the
        # frame makes the transform linear rather than circular, so a lag
        # does not wrap around and correlate the end with the beginning.
        spectrum = np.fft.rfft(block, n=frame * 2)
        correlation = np.fft.irfft(spectrum * np.conj(spectrum))[:frame]

        segment = correlation[lowest:highest + 1]
        if segment.size == 0:
            continue
        peak = int(np.argmax(segment))
        strength = float(segment[peak] / energy)
        if strength < VOICED_CORRELATION:
            continue

        lag = lowest + peak
        # Interpolate the peak against its neighbours. Without it the answer
        # is quantised to whole samples, which at 16 kHz is 12 Hz of error at
        # 250 Hz -- enough to matter when a decision sits on a threshold.
        if 0 < lag < frame - 1:
            before, here, after = (
                float(correlation[lag - 1]),
                float(correlation[lag]),
                float(correlation[lag + 1]),
            )
            divisor = before - 2.0 * here + after
            if divisor != 0.0:
                lag += 0.5 * (before - after) / divisor

        if lag > 0:
            found.append(rate / lag)

    if not found:
        return Pitch(0.0, 0.0, 0)
    return Pitch(float(np.median(found)), len(found) / max(1, total), len(found))
