"""Building a dubbed audio track from translated subtitles.

Each cue is spoken into the slot its original occupied, and the original is
ducked underneath rather than removed. Keeping it serves two purposes: a
listener can hear who is speaking and with what emphasis, and when the
translation is wrong -- which the numeric audit already warns about -- the
original is still there to be checked against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..audio.capture import FileSource
from ..audio.types import TARGET_SAMPLE_RATE
from ..subtitles.cues import Cue
from .speaker import Speaker, Utterance, resample

#: How far the original is turned down while the dub is speaking.
#:
#: -18 dB: audible enough to follow the speaker's voice and emotion, quiet
#: enough not to compete with the words being read out.
DUCK_GAIN = 0.125
#: Fade into and out of ducking, so the original does not jump in level.
DUCK_FADE = 0.15


@dataclass
class DubResult:
    samples: np.ndarray
    rate: int
    spoken: int = 0
    overran: int = 0
    tightest_scale: float = 1.0
    utterances: list[Utterance] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return len(self.samples) / self.rate

    @property
    def rushed(self) -> list[Utterance]:
        """Lines squeezed near the limit of what still sounds like speech."""
        return [u for u in self.utterances if u.length_scale < 0.80]


def synthesise_track(
    cues: tuple[Cue, ...],
    speaker: Speaker,
    total_seconds: float,
    rate: int = TARGET_SAMPLE_RATE,
) -> DubResult:
    """Speak every cue into its own slot on one timeline."""
    length = max(1, int((total_seconds + 2.0) * rate))
    track = np.zeros(length, dtype=np.float32)
    result = DubResult(samples=track, rate=rate)

    for cue in cues:
        text = cue.flat_text.strip()
        if not text:
            continue
        utterance = speaker.fit(text, cue.start, cue.duration)
        if utterance.samples.size == 0:
            continue

        voice = resample(utterance.samples, utterance.rate, rate)
        at = int(cue.start * rate)
        end = min(at + len(voice), length)
        if end > at:
            # Added rather than assigned: a line that runs into the next slot
            # overlaps it instead of cutting it off, which is how a person
            # talking over the end of a sentence sounds.
            track[at:end] += voice[: end - at]

        result.spoken += 1
        result.overran += int(utterance.overran)
        result.tightest_scale = min(result.tightest_scale, utterance.length_scale)
        result.utterances.append(utterance)

    peak = float(np.abs(track).max()) if track.size else 0.0
    if peak > 0.98:
        # Overlapping lines can sum past full scale, which clips audibly.
        track *= 0.98 / peak
    result.samples = track
    return result


def duck(original: np.ndarray, cues: tuple[Cue, ...], rate: int) -> np.ndarray:
    """Turn the original down wherever the dub is speaking."""
    gain = np.ones(len(original), dtype=np.float32)
    fade = max(1, int(DUCK_FADE * rate))

    for cue in cues:
        start = int(cue.start * rate)
        stop = min(int(cue.end * rate), len(original))
        if stop <= start:
            continue
        gain[start:stop] = np.minimum(gain[start:stop], DUCK_GAIN)
        # Ramp in and out so the level does not step.
        for edge, direction in ((start, -1), (stop, 1)):
            a = max(0, edge if direction > 0 else edge - fade)
            b = min(len(gain), (edge + fade) if direction > 0 else edge)
            if b > a:
                ramp = np.linspace(DUCK_GAIN, 1.0, b - a, dtype=np.float32)
                if direction < 0:
                    ramp = ramp[::-1]
                gain[a:b] = np.minimum(gain[a:b], ramp)
    return original * gain


def mix(
    media_path: Path | str,
    cues: tuple[Cue, ...],
    speaker: Speaker,
    total_seconds: float,
    keep_original: bool = True,
    rate: int = TARGET_SAMPLE_RATE,
) -> DubResult:
    """Dub a recording: speak the cues, duck the original, mix the two."""
    dub = synthesise_track(cues, speaker, total_seconds, rate=rate)
    if not keep_original:
        return dub

    blocks = [chunk.samples for chunk in FileSource(media_path).stream()]
    original = np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)
    if original.size < dub.samples.size:
        original = np.pad(original, (0, dub.samples.size - original.size))
    else:
        original = original[: dub.samples.size]

    mixed = duck(original, cues, rate) + dub.samples
    peak = float(np.abs(mixed).max()) if mixed.size else 0.0
    if peak > 0.98:
        mixed *= 0.98 / peak
    dub.samples = mixed
    return dub
