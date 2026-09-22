"""Building a dubbed audio track from translated subtitles.

Each cue is spoken into the slot its original occupied, and the original is
ducked underneath rather than removed. Keeping it serves two purposes: a
listener can hear who is speaking and with what emphasis, and when the
translation is wrong -- which the numeric audit already warns about -- the
original is still there to be checked against.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..audio.resample import pcm16_to_float32
from ..subtitles.cues import Cue
from ..mt.condense import slot_seconds
from . import casting
from .casting import Cast
from .speaker import NATIVE_RATE, Speaker, Utterance, VoiceBank, resample

#: The rate a dubbed soundtrack is built and written at.
#:
#: Piper speaks at 22050, and the rest of the program works at 16000 because
#: that is what the recogniser wants. Building the dub at the recogniser's rate
#: meant every spoken word was resampled down on its way out, throwing away
#: everything above 8 kHz -- the air in a voice, and most of what distinguishes
#: an "s" from an "f". Nothing downstream needed that: the soundtrack is for a
#: person to listen to, not for a model to read.
DUB_SAMPLE_RATE = NATIVE_RATE

#: How far the original is turned down while the dub is speaking.
#:
#: -18 dB: audible enough to follow the speaker's voice and emotion, quiet
#: enough not to compete with the words being read out.
DUCK_GAIN = 0.125
#: Fade into and out of ducking, so the original does not jump in level.
DUCK_FADE = 0.15

#: A silence shorter than this between two spoken lines is ducked through.
#:
#: The dub is turned down over the dub, not over the subtitle, because those
#: are not the same stretch of time: a translated line is usually shorter than
#: the line it translates, and holding the original down until the caption ends
#: leaves dead air. Measured on a five-minute talk: twelve such holes, up to
#: 2.0 s each, 13.9 s in all, at -18 dB over a speaker who was himself pausing
#: -- audible as the sound dropping out.
#:
#: But letting the original back up for every breath between two sentences is
#: its own fault: the level pumps. 0.7 s is long enough that opening it leaves
#: something to hear after the two 0.15 s fades, and short enough that an
#: ordinary pause between clauses stays closed.
DUCK_BRIDGE = 0.7

#: How far a line may begin before the moment it was said.
#:
#: The translation of a sentence rarely takes exactly as long as the sentence
#: did, and when it takes longer the choice is between starting early and
#: talking over the next line. Early wins: a dub that runs half a second ahead
#: of the picture is a dub, two voices at once is a mess. Bounded, and never
#: before the previous line has finished speaking, so the drift cannot
#: accumulate across a recording.
EARLY_START = 1.0


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
    rate: int = DUB_SAMPLE_RATE,
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

    spoken_until = 0.0
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

        # The slot runs to the start of the next line: the silence after a
        # line is time nothing else is using.
        slot = slot_seconds(cues, index)
        begin = cue.start
        utterance = voice.fit(text, begin, slot)

        if utterance.compressed:
            # The line does not fit at a natural pace. Before reading it
            # faster, spend the silence in front of it: that silence is time
            # nothing else is using, and a listener notices a line that starts
            # early far less than one that is gabbled.
            #
            # Only lines that would otherwise be squeezed. A line that fits
            # stays exactly where it was said -- moving those too would walk
            # the whole dub forward for no reason, which is what the first
            # version of this did.
            earlier = max(spoken_until, cue.start - EARLY_START)
            if earlier < cue.start - 1e-3:
                begin = earlier
                roomier = voice.fit(
                    text, begin, max(0.05, cue.start + slot - begin)
                )
                # Keep it only if the extra room actually bought a gentler
                # pace; otherwise the line may as well stay where it was said.
                if roomier.length_scale > utterance.length_scale + 1e-3:
                    utterance = roomier
                else:
                    begin = cue.start
        if utterance.samples.size == 0:
            continue

        samples = resample(utterance.samples, utterance.rate, rate)
        at = int(begin * rate)
        end = min(at + len(samples), length)
        if end > at:
            # Added rather than assigned: a line that runs into the next slot
            # overlaps it instead of cutting it off, which is how a person
            # talking over the end of a sentence sounds.
            track[at:end] += samples[: end - at]

        spoken_until = begin + utterance.duration
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


def spoken_spans(
    utterances: list[Utterance], bridge: float = DUCK_BRIDGE
) -> list[tuple[float, float]]:
    """When the dub is actually speaking, with short silences bridged over."""
    spans: list[tuple[float, float]] = []
    for utterance in utterances:
        if utterance.samples.size == 0:
            continue
        start, end = utterance.start, utterance.start + utterance.duration
        if spans and start - spans[-1][1] <= bridge:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((start, end))
    return spans


def duck(
    original: np.ndarray, spans: Sequence[tuple[float, float]], rate: int
) -> np.ndarray:
    """Turn the original down over each of `spans`."""
    gain = np.ones(len(original), dtype=np.float32)
    fade = max(1, int(DUCK_FADE * rate))

    for begin, finish in spans:
        start = int(begin * rate)
        stop = min(int(finish * rate), len(original))
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
    rate: int = DUB_SAMPLE_RATE,
    match_voices: bool = False,
    speaker_model: Path | str | None = None,
) -> DubResult:
    """Dub a recording: speak the cues, duck the original, mix the two.

    With `match_voices`, the original is measured first and each line is read
    by a voice of the same register. With a `speaker_model` too, the people
    are told apart by their voices first and each person gets one register
    (`lt_core.tts.speakers`); pitch alone could not split a man and a woman
    who share one. That needs the original audio whether or
    not it is kept in the mix, which is why it is loaded before anything is
    spoken.
    """
    original = _load(media_path, rate) if (keep_original or match_voices) else None

    cast = None
    if match_voices and original is not None and isinstance(speaker, VoiceBank):
        people = _people(cues, original, rate, speaker_model)
        if people is not None:
            cast = casting.cast_people(cues, original, rate, people)
        else:
            cast = casting.analyse(cues, original, rate)

    dub = synthesise_track(cues, speaker, total_seconds, rate=rate, cast=cast)
    if not keep_original or original is None:
        return dub

    if original.size < dub.samples.size:
        original = np.pad(original, (0, dub.samples.size - original.size))
    else:
        original = original[: dub.samples.size]

    mixed = duck(original, spoken_spans(dub.utterances), rate) + dub.samples
    peak = float(np.abs(mixed).max()) if mixed.size else 0.0
    if peak > 0.98:
        mixed *= 0.98 / peak
    dub.samples = mixed
    return dub


def _people(cues, original: np.ndarray, rate: int, model) -> list[int] | None:
    """Who speaks each cue, or None when the speaker model is not to hand."""
    if model is None:
        return None
    try:
        from . import speakers

        voice_rate = 16_000
        audio = resample(original, rate, voice_rate)
        return speakers.speaker_of(speakers.identify(cues, audio, voice_rate, model), cues)
    except Exception:  # noqa: BLE001 -- no model, no sherpa: pitch alone
        return None


def _load(media_path: Path | str, rate: int) -> np.ndarray:
    """The whole recording as one array, at the rate the dub is built at.

    Decoded here rather than through `FileSource`, which exists to feed the
    recogniser and is fixed at its rate. A dub is not being recognised.
    """
    import subprocess

    import imageio_ffmpeg

    # Store-Python virtualises paths given to subprocesses; resolve first.
    exe = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve())
    done = subprocess.run(
        [exe, "-nostdin", "-loglevel", "error",
         "-i", str(Path(media_path).resolve()),
         "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(rate), "-"],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    raw = done.stdout[: len(done.stdout) // 2 * 2]
    if not raw:
        # The file was already probed and read once by now, so this is not the
        # place to fail a job: a dub without the original under it is still a
        # dub, and the caller pads what is missing.
        return np.zeros(0, dtype=np.float32)
    return pcm16_to_float32(raw)
