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


@dataclass(frozen=True)
class Transcript:
    segments: tuple[Segment, ...]
    language: str
    language_probability: float
    duration: float
    # Wall-clock seconds spent transcribing, for reporting a real-time factor.
    elapsed: float = 0.0
    model: str = ""

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
