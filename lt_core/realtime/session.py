"""Live translation: audio in, subtitles out, while the speaker is still talking.

The shape of the problem is set by one measurement from the Day 0 spike: the
whole chain -- recognise, translate, start speaking -- costs about 830 ms of
compute. Perceived delay is therefore almost entirely the size of the audio
window we wait for before running anything, not the speed of the models.

    perceived delay ~= window + 0.83 s

That makes the window a dial the user can hold, rather than an architectural
constant. A short window answers fast and revises itself more; a long one is
steadier and later. Both are legitimate, so both are offered.

What is never negotiable is that committed text stays committed. Text that
changes after being shown cannot be spoken aloud, written to a file, or read
by a person who has already moved on.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np

from .. import languages
from ..asr.transcriber import TranscribeOptions, Transcriber
from ..asr.types import Word
from ..audio.types import TARGET_SAMPLE_RATE, AudioChunk
from ..mt.translator import Translator
from .agreement import LocalAgreement

_SENTENCE_END = re.compile(r"[.!?…。！？]['\"»”’)\]］】」』]*\s*$")
_CLAUSE_END = re.compile(r"[,;:—–、，；：]['\"»”’)\]]*\s*$")

#: How long a sentence may go unfinished before part of it is committed anyway.
#:
#: Long, because this is the safety valve and not the answer to latency: the
#: provisional translation below is what keeps a reader current while a
#: sentence is still being spoken. Cutting the committed translation at clauses
#: instead was measured and costs meaning -- "mass times energy times
#: coordination", handed over a clause at a time, came back as "масса во время
#: энергии", because "times" without its sentence is the preposition.
#:
#: Ordinary speech runs six to ten seconds to a sentence. The longest real one
#: measured here was twenty, so at eight the valve was doing the work and
#: producing exactly that fault; at twenty-four it never fires on this
#: recording and still bounds a speaker who genuinely never stops.
HOLD_LIMIT = 24.0

#: Never hand the translator fewer than this many words on its own. A fragment
#: is what makes the model invent -- measured on Day 3, "Yes." came back as
#: "Нет, нет."
MIN_CLAUSE_WORDS = 4


@dataclass(frozen=True)
class Pace:
    """The latency/steadiness dial.

    `window` is how much new audio accumulates before the transcriber runs
    again. `context` is how much already-committed audio stays in the buffer:
    the model transcribes far better when a phrase does not begin at the very
    first sample it can see.
    """

    window: float
    context: float = 3.0
    #: Hard cap on buffer length. Without one, a speaker who never pauses and
    #: never repeats themselves grows the buffer until each pass takes longer
    #: than the audio it covers, and the session falls behind for good.
    max_buffer: float = 28.0
    #: How far the commit point may fall behind the audio before its prefix is
    #: accepted without a second opinion.
    #
    #: Agreement confirms only a prefix, so one word the model will not settle
    #: on blocks everything behind it -- measured at fourteen seconds on the
    #: reference clip, over a single "31%".
    #
    #: Measured as a lag rather than as "how long since anything committed".
    #: The first version asked the latter and almost never fired: a single
    #: trailing word agreeing advanced the commit point by hundredths of a
    #: second and reset the timer, while the stream stood still behind it.
    max_lag: float = 4.0

    @property
    def expected_delay(self) -> float:
        """Roughly how far behind the speaker the committed text runs.

        Two windows, not one. A word cannot be committed on the tick it first
        appears -- agreement needs a second hypothesis, which arrives a window
        later. The first version of this promised `window + 0.85` and was
        wrong by a whole window, which measurement caught.
        """
        return 2 * self.window + 0.9


FAST = Pace(window=1.0, max_lag=3.0)
"""~1.9 s. Text appears quickly and corrects itself more often."""

BALANCED = Pace(window=2.0, max_lag=5.0)
"""~2.9 s. The default."""

STEADY = Pace(window=4.0, max_lag=8.0)
"""~4.9 s. Text arrives late and almost never changes."""

PACES = {"fast": FAST, "balanced": BALANCED, "steady": STEADY}


@dataclass(frozen=True)
class LiveUpdate:
    """One tick's worth of change, ready to put on screen."""

    #: Text confirmed on this tick. Never revised afterwards.
    committed: str = ""
    #: The provisional tail. Replaced wholesale on the next tick.
    partial: str = ""
    #: Translation of whatever sentences completed on this tick.
    translation: str = ""
    #: The sentence still being spoken, translated provisionally. Replaced
    #: wholesale on the next tick, exactly as `partial` is, and superseded by
    #: `translation` once the sentence finishes.
    partial_translation: str = ""
    #: Which side of a two-person conversation this belongs to.
    speaker: str | None = None
    #: Seconds of audio consumed by the session so far.
    audio_time: float = 0.0
    #: Seconds between the audio arriving and this update existing.
    latency: float = 0.0

    @property
    def has_content(self) -> bool:
        return bool(
            self.committed or self.partial
            or self.translation or self.partial_translation
        )


@dataclass
class SessionStats:
    ticks: int = 0
    asr_seconds: float = 0.0
    mt_seconds: float = 0.0
    audio_seconds: float = 0.0
    #: Every tick's lag: how far the committed text trails the audio.
    #:
    #: Defined as consumed_audio - committed_until and nothing else. An earlier
    #: version added the tick's own compute time to it and produced 43 seconds
    #: on a session whose buffer never exceeded 6 -- a number with no defensible
    #: meaning. This one is a plain distance between two clocks.
    lags: list[float] = field(default_factory=list)
    max_buffer_seconds: float = 0.0
    forced_trims: int = 0
    forced_commits: int = 0
    #: Total words committed over the session.
    #:
    #: Counted here rather than read from the agreement's list, which is a
    #: rolling window trimmed to bound memory. Reporting its length as "words
    #: transcribed" understated a 15-minute session by an order of magnitude.
    committed_words: int = 0

    @property
    def median_lag(self) -> float:
        import statistics

        return statistics.median(self.lags) if self.lags else 0.0

    @property
    def worst_lag(self) -> float:
        return max(self.lags) if self.lags else 0.0

    @property
    def realtime_factor(self) -> float:
        """Compute per second of audio. Above 1.0 means falling behind."""
        if not self.audio_seconds:
            return 0.0
        return (self.asr_seconds + self.mt_seconds) / self.audio_seconds


class LiveSession:
    """Runs one live translation from a stream of audio chunks."""

    def __init__(
        self,
        transcriber: Transcriber,
        translator: Translator | None = None,
        source_language: str | None = None,
        target_language: str | None = None,
        pace: Pace = BALANCED,
        speaker: str | None = None,
        carry_context: bool = True,
    ) -> None:
        self.transcriber = transcriber
        self.translator = translator
        self.source_language = source_language
        self.target_language = target_language
        self.pace = pace
        self.speaker = speaker
        # Carrying previously committed text forward keeps a monologue reading
        # as prose. In a two-language conversation it does the opposite: that
        # text is in the previous speaker's language and drags the model into
        # transcribing the next speaker in it too. Measured -- a German turn
        # came out as Russian, and its translation degenerated into "The
        # system." repeated five times.
        #
        # The punctuated sample is a different thing and is always sent: it is
        # not anybody's words, it is an example of what a finished sentence
        # looks like, and it is chosen for the language of the window in hand.
        self.carry_context = carry_context
        #: Filled in on the first tick when the language was not given.
        self.detected_language: str | None = source_language

        self.agreement = LocalAgreement()
        self.stats = SessionStats()

        self._buffer = np.zeros(0, dtype=np.float32)
        self._buffer_start = 0.0
        self._consumed = 0.0
        self._last_run_at = 0.0
        self._untranslated: list[Word] = []
        #: The last provisional translation, and the text it was made from, so
        #: a sentence that has not grown is not translated again.
        self._preview: tuple[str, str] = ("", "")
        self._lock = threading.Lock()

    # -- feeding ---------------------------------------------------------
    def feed(self, chunk: AudioChunk) -> LiveUpdate | None:
        """Add audio; get an update back when the window has filled."""
        with self._lock:
            self._buffer = np.concatenate([self._buffer, chunk.samples])
            self._consumed = chunk.end_time
            self.stats.audio_seconds = self._consumed
            self.stats.max_buffer_seconds = max(
                self.stats.max_buffer_seconds, self._buffer_duration
            )

            if self._consumed - self._last_run_at < self.pace.window:
                return None
            self._last_run_at = self._consumed

        return self._tick(arrived_at=time.perf_counter())

    def run(self, chunks: Iterator[AudioChunk]) -> Iterator[LiveUpdate]:
        """Consume a stream, yielding updates as they are produced."""
        for chunk in chunks:
            update = self.feed(chunk)
            if update is not None and update.has_content:
                yield update
        final = self.finish()
        if final.has_content:
            yield final

    def finish(self) -> LiveUpdate:
        """End the session: commit the tail and translate what is left."""
        with self._lock:
            tail = self.agreement.flush()
            self.stats.committed_words += len(tail)
            self._untranslated.extend(tail)
            translation = self._translate(force=True)
            return LiveUpdate(
                committed="".join(word.text for word in tail).strip(),
                partial="",
                translation=translation,
                speaker=self.speaker,
                audio_time=self._consumed,
            )

    # -- internals -------------------------------------------------------
    @property
    def _buffer_duration(self) -> float:
        return len(self._buffer) / TARGET_SAMPLE_RATE

    def _tick(self, arrived_at: float) -> LiveUpdate | None:
        with self._lock:
            audio = self._buffer.copy()
            buffer_start = self._buffer_start
        if audio.size < TARGET_SAMPLE_RATE // 4:
            return None

        started = time.perf_counter()
        transcript = self.transcriber.transcribe(
            audio,
            TranscribeOptions(
                language=self.source_language,
                # Conditioning on previous text is what makes a live transcript
                # read as continuous prose rather than as disconnected
                # fragments, and here the previous text is committed, so a bad
                # guess cannot poison what follows.
                initial_prompt=self._prompt(),
                # Silence is common between phrases and the filter costs almost
                # nothing, but on a two-second window it can swallow a short
                # word at the edge, so it is left off for the live path.
                vad_filter=False,
                # File mode primes the model with a punctuated sample, after
                # detecting the language to pick the right one. Here that
                # detection would run on every two-second window, and this
                # path already carries its own context above.
                punctuation_prompt=False,
                # File mode carries the previous window's text forward, which
                # is what makes it punctuate. Here a window is two seconds and
                # the text before it is already supplied above, deliberately,
                # as committed words only.
                condition_on_previous_text=False,
            ),
            total_duration=len(audio) / TARGET_SAMPLE_RATE,
        )
        self.stats.asr_seconds += time.perf_counter() - started
        self.stats.ticks += 1

        if self.source_language is None and transcript.language:
            # Detect once, then pin. Re-detecting every tick lets the model
            # change its mind mid-session on a short or accented window, and a
            # translation whose source language flips halfway through is worse
            # than one that is confidently wrong about a single word.
            self.source_language = transcript.language
            self.detected_language = transcript.language

        words = [
            Word(
                text=word.text,
                start=buffer_start + word.start,
                end=buffer_start + word.end,
                probability=word.probability,
            )
            for word in transcript.words
        ]

        with self._lock:
            committed = self.agreement.insert(words)

            lag = self._consumed - self.agreement.committed_until
            if lag > self.pace.max_lag:
                # Too far behind. Accept the pending words that are no longer
                # at the edge of the buffer, where more audio could still
                # change them.
                forced = self.agreement.force_commit_before(
                    self._consumed - self.pace.window
                )
                if forced:
                    self.stats.forced_commits += 1
                    committed = committed + forced

            self.stats.committed_words += len(committed)
            self._untranslated.extend(committed)
            partial = self.agreement.pending_text()
            self._trim()
            translation = self._translate()
            preview = self._provisional()

        latency = self._consumed - self.agreement.committed_until
        self.stats.lags.append(latency)

        return LiveUpdate(
            committed="".join(word.text for word in committed).strip(),
            partial=partial,
            translation=translation,
            partial_translation=preview,
            speaker=self.speaker,
            audio_time=self._consumed,
            latency=latency,
        )

    def _provisional(self) -> str:
        """The sentence still being spoken, translated as it stands.

        Committed translations wait for a full stop, because a clause handed
        over on its own loses what the sentence was doing with it. That is the
        right rule for text nobody will revise -- and on its own it leaves a
        reader with nothing while a long sentence is spoken: measured on a real
        talk, the first translation arrived 40 seconds in.

        So the unfinished sentence is translated too, and marked as
        provisional. It is replaced on the next tick and then superseded by the
        real thing, which is the same contract the original text already has.

        Called with the lock held.
        """
        if self.translator is None or not self.target_language:
            return ""
        if not self._untranslated or not self.source_language:
            self._preview = ("", "")
            return ""

        text = "".join(word.text for word in self._untranslated).strip()
        if not text:
            return ""
        if text == self._preview[0]:
            # Nothing was added this tick; do not pay for the same answer.
            return self._preview[1]

        started = time.perf_counter()
        try:
            results, _ = self.translator.translate(
                [text], self.source_language, self.target_language
            )
        except Exception:  # noqa: BLE001 -- provisional text, never fatal
            return ""
        finally:
            self.stats.mt_seconds += time.perf_counter() - started
        answer = results[0] if results else ""
        self._preview = (text, answer)
        return answer

    def _overdue_cut(self) -> int:
        """Where to break a sentence that is taking too long to finish.

        At a comma: the model translates a clause well, and a clause is not the
        fragment that makes it invent. A run that has gone twice the limit with
        no comma in it either is released whole rather than held any longer --
        the translator splits long input at clause boundaries of its own.
        """
        held = self._untranslated
        if not held:
            return -1
        waiting = self._consumed - held[0].start
        if waiting < HOLD_LIMIT:
            return -1
        for index in range(len(held) - 1, MIN_CLAUSE_WORDS - 1, -1):
            if _CLAUSE_END.search(held[index].text.strip()):
                return index
        return len(held) - 1 if waiting >= 2 * HOLD_LIMIT else -1

    def _prompt(self) -> str | None:
        """Context for the next pass: a punctuated opening, then what was said.

        The sample is the same device file mode uses, and for the same reason:
        without a punctuated example this model transcribes continuous speech
        as one unbroken run. Live that is worse than untidy -- a sentence is
        what releases a translation, so a passage with no full stop in it is a
        passage nobody reads until it ends. Measured on a five-minute talk, the
        opening sentence ran 36 seconds.

        It stays in front of the committed tail rather than seeding only the
        first pass. The tail is what the model just produced, so if it comes
        back unpunctuated once, a prompt made only of it keeps it that way.
        """
        opening = languages.punctuation_sample(self.source_language or "")
        if not self.carry_context:
            return opening or None
        tail = self.agreement.committed[-30:]
        text = "".join(word.text for word in tail).strip()
        return " ".join(part for part in (opening, text) if part) or None

    def _trim(self) -> None:
        """Drop audio that is settled, keeping a little for context.

        Called with the lock held.
        """
        keep_from = self.agreement.committed_until - self.pace.context
        if self._buffer_duration > self.pace.max_buffer:
            # Nothing has been agreed for a long time -- a monologue with no
            # pauses, or a stretch the model keeps re-reading differently. Cut
            # anyway: an unbounded buffer makes every pass slower than the
            # audio it covers, and the session never recovers.
            keep_from = max(
                keep_from,
                self._buffer_start + self._buffer_duration - self.pace.max_buffer / 2,
            )
            self.stats.forced_trims += 1

        offset = keep_from - self._buffer_start
        if offset <= 0:
            return
        samples = int(offset * TARGET_SAMPLE_RATE)
        if samples >= len(self._buffer):
            samples = len(self._buffer)
        self._buffer = self._buffer[samples:]
        self._buffer_start += samples / TARGET_SAMPLE_RATE
        # History beyond the prompt window is never read again.
        self.agreement.forget_before(self._buffer_start - 60.0)

    def _translate(self, force: bool = False) -> str:
        """Translate committed text, one complete sentence at a time.

        Sentences rather than words, because a translator given a fragment
        invents an ending for it -- measured on Day 3, where "Yes." came back
        as "Нет, нет." A sentence that has not finished waits for the next
        tick; at end of session there is no next tick, so `force` takes
        whatever is there.

        The sentences that *are* finished go now, and only the unfinished tail
        waits. Asking whether the whole accumulation ends on a full stop meant
        a completed sentence sat unread until a later commit happened to land
        exactly on one: measured on a five-minute talk, the first translation
        appeared at 40 s, they arrived a median of 10 s apart, and one of them
        was 496 characters of text delivered at once.
        """
        if self.translator is None or not self.target_language:
            self._untranslated.clear()
            return ""
        if not self._untranslated or not self.source_language:
            return ""

        if force:
            ready, self._untranslated = self._untranslated, []
        else:
            last = -1
            for index, word in enumerate(self._untranslated):
                if _SENTENCE_END.search(word.text):
                    last = index
            if last < 0:
                last = self._overdue_cut()
            if last < 0:
                return ""
            ready = self._untranslated[: last + 1]
            self._untranslated = self._untranslated[last + 1:]

        text = "".join(word.text for word in ready).strip()
        if not text:
            return ""
        self._preview = ("", "")
        started = time.perf_counter()
        try:
            results, _ = self.translator.translate(
                [text], self.source_language, self.target_language
            )
        except Exception:
            # A live session must not die because one sentence failed to
            # translate; the original is already on screen either way.
            return ""
        finally:
            self.stats.mt_seconds += time.perf_counter() - started
        return results[0] if results else ""
