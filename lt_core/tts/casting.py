"""Deciding which voice speaks which line.

A dub with one voice tells a two-person conversation as a monologue. The
listener loses track of who is talking, and in an interview or a negotiation
that is most of the content.

So each line is measured and given a voice that matches: low voices are read
by the male voice, high voices by the female one. What that costs when it is
wrong is an interruption of one line, not of the recording, which is why a
per-line decision is worth making at all.

The threshold is taken from the recording itself where the recording supports
one. Measured on four real files (`docs/DAY7.md`): pitch is bimodal when two
people are present, with an empty band between roughly 120 and 160 Hz, and
the middle of a file's own gap separates its speakers better than any fixed
number can. A fixed number is still needed when only one person is talking,
and 155 Hz is where that falls -- inside the empty band on every file
measured, and the classical ceiling of the male modal range.

Which voice per line is decided only where the recording showed two people.
Where it showed one, that fixed number chooses the voice for the recording and
then stays out of the way: a single speaker's pitch crosses any threshold you
care to name in the course of a talk, and a line-by-line comparison turns that
into a narrator who changes sex mid-paragraph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..audio.pitch import Pitch, estimate
from ..subtitles.cues import Cue

MALE, FEMALE = "male", "female"

#: Where a voice stops being low and starts being high, when the recording
#: gives no better answer.
DEFAULT_SPLIT = 155.0

#: Two clusters closer than this are one speaker whose pitch moved, not two
#: people. Measured separations between a real pair ran 40-80 Hz; a single
#: speaker's own spread across a recording stayed well under this.
MIN_SEPARATION = 35.0

#: How wide the band between the two groups must be before it counts as two
#: people.
#:
#: Two-means will cut any list of numbers in half, including one speaker's own
#: spread, and the halves it produces are always a little apart -- so "the
#: groups are separated" is not evidence of anything. What is evidence is an
#: *empty* band: nothing measured in the middle at all. Across every recording
#: on hand, genuine pairs left 63-88 Hz empty, while one person talking left
#: 0.2-2.0 Hz, the two halves touching, which is what a continuous spread looks
#: like after it has been cut. 25 Hz sits an order of magnitude above the false
#: ones and well below the narrowest true one.
#:
#: Without this a 5-minute talk by one man came out with 16 of its 74 lines
#: read by a woman: his pitch ran 115-231 Hz, two-means put the boundary at
#: 167, and every animated sentence crossed it.
MIN_EMPTY_BAND = 25.0

#: Within this much of the split, a line is not decided on its own. It takes
#: the decision of the lines around it, because a speaker does not change sex
#: for one sentence and then change back.
UNCERTAIN_BAND = 12.0


@dataclass
class Cast:
    """Which voice reads each cue, and how well founded that is."""

    #: One gender per cue, in cue order.
    genders: list[str] = field(default_factory=list)
    #: The measured pitch per cue; `None` where nothing voiced was found.
    pitches: list[Pitch | None] = field(default_factory=list)
    #: The threshold actually used, in Hz.
    split: float = DEFAULT_SPLIT
    #: True when the recording itself supported the threshold, rather than
    #: falling back to the default.
    from_recording: bool = False
    #: Cues with no usable pitch, which were given the recording's main voice.
    unmeasured: int = 0

    @property
    def voices_used(self) -> set[str]:
        return set(self.genders)

    @property
    def is_mixed(self) -> bool:
        """Whether this recording actually needed two voices."""
        return len(self.voices_used) > 1

    def summary(self) -> str:
        if not self.genders:
            return "Голоса не определялись."
        male = self.genders.count(MALE)
        female = self.genders.count(FEMALE)
        source = "по записи" if self.from_recording else "по умолчанию"
        if not self.is_mixed:
            voice = "мужской" if male else "женский"
            text = f"Один голос: {voice} (порог {self.split:.0f} Гц, {source})"
        else:
            text = (
                f"Голоса: {male} мужских, {female} женских "
                f"(порог {self.split:.0f} Гц, {source})"
            )
        if self.unmeasured:
            text += f"; {self.unmeasured} без различимого тона"
        return text


def _cluster(values: np.ndarray) -> tuple[float, float, float]:
    """Split pitches into a low and a high group; return centres and the gap.

    One-dimensional two-means. Started from the extremes rather than at
    random so the answer is the same every run -- a dub that assigns voices
    differently on a second pass over the same file is not a dub anyone can
    check.
    """
    low, high = float(values.min()), float(values.max())
    for _ in range(30):
        lower = values[np.abs(values - low) <= np.abs(values - high)]
        upper = values[np.abs(values - low) > np.abs(values - high)]
        if lower.size == 0 or upper.size == 0:
            return low, high, 0.0
        new_low, new_high = float(lower.mean()), float(upper.mean())
        if abs(new_low - low) < 0.1 and abs(new_high - high) < 0.1:
            low, high = new_low, new_high
            break
        low, high = new_low, new_high

    lower = values[np.abs(values - low) <= np.abs(values - high)]
    upper = values[np.abs(values - low) > np.abs(values - high)]
    if lower.size == 0 or upper.size == 0:
        return low, high, 0.0
    # The gap between the groups, not between their centres: that is where a
    # threshold belongs, and it is what the measurements showed as empty.
    return low, high, float(upper.min() - lower.max())


def choose_split(pitches: list[float]) -> tuple[float, bool]:
    """A threshold for this recording, and whether the recording gave it."""
    values = np.array([p for p in pitches if p > 0.0], dtype=np.float64)
    if values.size < 4:
        return DEFAULT_SPLIT, False

    low, high, gap = _cluster(values)
    if high - low < MIN_SEPARATION or gap < MIN_EMPTY_BAND:
        # One speaker, or two of the same register. A single voice reads it.
        return DEFAULT_SPLIT, False

    lower = values[values <= low + (high - low) / 2]
    upper = values[values > low + (high - low) / 2]
    return float((lower.max() + upper.min()) / 2), True


def analyse(
    cues: tuple[Cue, ...],
    audio: np.ndarray,
    rate: int,
    default: str | None = None,
) -> Cast:
    """Measure each cue in the original audio and cast a voice to it."""
    cast = Cast()
    if not cues:
        return cast

    measured: list[Pitch | None] = []
    for cue in cues:
        start = max(0, int(cue.start * rate))
        stop = min(audio.size, int(cue.end * rate))
        if stop <= start:
            measured.append(None)
            continue
        pitch = estimate(audio[start:stop], rate)
        measured.append(pitch if pitch.confident else None)

    cast.pitches = measured
    confident = [p.median for p in measured if p is not None]
    cast.split, cast.from_recording = choose_split(confident)

    # The recording's main voice, for cues that could not be measured. Silence
    # and applause get whoever does most of the talking, which is a better
    # guess than always the same one.
    if confident:
        majority = MALE if float(np.median(confident)) < cast.split else FEMALE
    else:
        majority = default or MALE

    cast.unmeasured = sum(1 for pitch in measured if pitch is None)

    if not cast.from_recording:
        # Nothing in this recording says there are two people in it, so the
        # threshold only decides which voice reads the whole of it -- never
        # which voice reads a line. One person's pitch wanders a long way
        # over five minutes: an animated sentence from the same man can
        # measure 230 Hz where his calm ones measure 120, and comparing each
        # line against a fixed number turns that wandering into a cast
        # change. A register that is wrong throughout is a smaller fault than
        # a narrator who keeps changing sex.
        cast.genders = [majority] * len(measured)
        return cast

    genders = [
        majority if pitch is None
        else (MALE if pitch.median < cast.split else FEMALE)
        for pitch in measured
    ]
    cast.genders = _smooth(genders, measured, cast.split)
    return cast


def _smooth(
    genders: list[str], pitches: list[Pitch | None], split: float
) -> list[str]:
    """Let a borderline line follow its neighbours.

    Only lines whose pitch sits within `UNCERTAIN_BAND` of the threshold are
    moved, and only when both neighbours agree against them. A line clearly
    in one register is never overruled by context -- that would hide a real
    speaker change, which is the thing this is all for.
    """
    result = list(genders)
    for index in range(1, len(result) - 1):
        pitch = pitches[index]
        if pitch is None:
            continue
        if abs(pitch.median - split) > UNCERTAIN_BAND:
            continue
        before, after = result[index - 1], result[index + 1]
        if before == after and before != result[index]:
            result[index] = before
    return result
