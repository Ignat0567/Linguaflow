"""Transcription results.

A transcript is kept as segments of words, each word carrying its own timing.
Segment-level timing alone would be enough to print a transcript, but not to
build subtitles: Whisper emits segments up to 30 seconds long, and a subtitle
that sits on screen for 30 seconds is not a subtitle. Splitting one into
readable cues requires knowing where inside it each word falls.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    probability: float = 1.0

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Segment:
    """One stretch of speech as the model chose to divide it."""

    text: str
    start: float
    end: float
    words: tuple[Word, ...] = field(default=())
    # Mean log-probability over the segment's tokens. Whisper hallucinates on
    # silence and music, and those inventions score much lower than real
    # speech, so this is the handle for filtering them out.
    avg_logprob: float = 0.0
    no_speech_probability: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start


#: How sure the detector must be before its disagreement is worth raising.
#: A verdict over the opening minutes, not a lean.
CERTAIN_ENOUGH = 0.85


@dataclass(frozen=True)
class Transcript:
    segments: tuple[Segment, ...]
    language: str
    language_probability: float
    duration: float
    # Wall-clock seconds spent transcribing, for reporting a real-time factor.
    elapsed: float = 0.0
    model: str = ""

    # What the audio was taken to be on its own evidence, and how sure of it.
    #
    # The same as `language` whenever the language was detected; different when
    # the caller named one and the recording holds another. Worth knowing,
    # because Whisper does not object: told that a Russian recording is
    # English, it writes fluent English prose that no reader could tell from a
    # transcript. Measured on a twelve-minute file whose container defaults to
    # a dubbed Russian track -- 2718 words of real English in the original,
    # 1145 words of invented English from the dub, and nothing anywhere in the
    # output to say so.
    detected_language: str = ""
    detected_probability: float = 0.0

    @property
    def confidence_in_language(self) -> float | None:
        """How sure the language used is right, or None when nothing says so.

        Whisper reports a probability of 1.0 for any language it was handed,
        because it never checked -- a number that says only that it was told.
        Where the recording was checked, the detector's own answer stands
        behind it; where the detector disagreed, nothing does.
        """
        if not self.detected_language:
            return self.language_probability
        if self.detected_language == self.language:
            return self.detected_probability
        return None

    @property
    def language_looks_wrong(self) -> bool:
        """The recording is confidently in a language other than the one used.

        Detection is fallible too, and a warning raised over a correct choice
        teaches people to ignore warnings, so this asks for a verdict rather
        than a lean.
        """
        return (
            bool(self.detected_language)
            and self.detected_language != self.language
            and self.detected_probability >= CERTAIN_ENOUGH
        )


    @property
    def text(self) -> str:
        return " ".join(segment.text.strip() for segment in self.segments).strip()

    @property
    def words(self) -> tuple[Word, ...]:
        return tuple(word for segment in self.segments for word in segment.words)

    @property
    def speech_duration(self) -> float:
        return sum(segment.duration for segment in self.segments)

    @property
    def realtime_factor(self) -> float:
        return self.elapsed / self.duration if self.duration else 0.0
