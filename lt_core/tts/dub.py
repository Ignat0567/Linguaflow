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
from . import casting
from .casting import Cast
from .speaker import Speaker, Utterance, VoiceBank, resample

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
    #: Which voice read which line, when the recording had more than one
    #: speaker in it. Empty when a single voice read the whole thing.
    cast: Cast | None = None

    @property
    def duration(self) -> float:
        return len(self.samples) / self.rate

    @property
    def rushed(self) -> list[Utterance]:
        """Lines squeezed near the limit of what still sounds like speech."""
        return [u for u in self.utterances if u.length_scale < 0.80]

    @property
    def voices(self) -> dict[str, int]:
        """How many lines each voice read."""
        counts: dict[str, int] = {}
        for utterance in self.utterances:
            if utterance.voice:
                counts[utterance.voice] = counts.get(utterance.voice, 0) + 1
        return counts


def synthesise_track(
    cues: tuple[Cue, ...],
    speaker: Speaker | VoiceBank,
    total_seconds: float,
    rate: int = TARGET_SAMPLE_RATE,
    cast: Cast | None = None,
) -> DubResult:
    """Speak every cue into its own slot on one timeline.

    `speaker` may be a single voice or a bank of them. With a bank and a
    `cast`, each line is read by the voice cast to it, so a two-person
    recording comes out as two people.
    """
    length = max(1, int((total_seconds + 2.0) * rate))
    track = np.zeros(length, dtype=np.float32)
    result = DubResult(samples=track, rate=rate, cast=cast)

    for index, cue in enumerate(cues):
        text = cue.flat_text.strip()
        if not text:
            continue

        voice = speaker
        if isinstance(speaker, VoiceBank):
            gender = ""
            if cast is not None and index < len(cast.genders):
                gender = cast.genders[index]
            voice = speaker.for_gender(gender)

        utterance = voice.fit(text, cue.start, cue.duration)
        if utterance.samples.size == 0:
            continue

        samples = resample(utterance.samples, utterance.rate, rate)
        at = int(cue.start * rate)
        end = min(at + len(samples), length)
        if end > at:
            # Added rather than assigned: a line that runs into the next slot
            # overlaps it instead of cutting it off, which is how a person
            # talking over the end of a sentence sounds.
            track[at:end] += samples[: end - at]

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
    speaker: Speaker | VoiceBank,
    total_seconds: float,
    keep_original: bool = True,
    rate: int = TARGET_SAMPLE_RATE,
    match_voices: bool = False,
) -> DubResult:
    """Dub a recording: speak the cues, duck the original, mix the two.

    With `match_voices`, the original is measured first and each line is read
    by a voice of the same register. That needs the original audio whether or
    not it is kept in the mix, which is why it is loaded before anything is
    spoken.
    """
    original = _load(media_path, rate) if (keep_original or match_voices) else None

    cast = None
    if match_voices and original is not None and isinstance(speaker, VoiceBank):
        cast = casting.analyse(cues, original, rate)

    dub = synthesise_track(cues, speaker, total_seconds, rate=rate, cast=cast)
    if not keep_original or original is None:
        return dub

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


def _load(media_path: Path | str, rate: int) -> np.ndarray:
    blocks = [chunk.samples for chunk in FileSource(media_path).stream()]
    return np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)
