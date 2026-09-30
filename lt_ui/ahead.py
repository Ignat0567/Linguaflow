"""Translating a recorded video ahead of the viewer, not behind them.

Live translation cannot be ahead of speech, and has to wait for a sentence to
end before translating it -- cutting at clauses was measured and breaks the
meaning. On a German talk with 10-15 s sentences that put subtitles 10-15 s
behind the speaker and the voice later still: «very far behind, and it
stalls».

A video on YouTube is not live. Its sound can be fetched in seconds and put
through the file pipeline -- recognition over the whole recording, the
language detected from it, translation in whole sentences with all their
context -- and then shown and spoken *on the video's own clock*: each line at
its own timestamp, following pauses and seeks, never behind.
"""

from __future__ import annotations

import bisect
import queue
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from lt_core.messages import say


@dataclass(frozen=True)
class Line:
    start: float
    end: float
    original: str
    translated: str
    #: "male" / "female" when the original was measured, "" when not.
    voice: str = ""


class Track:
    """Translated lines on the video's timeline."""

    def __init__(self, lines: list[Line], language: str = "") -> None:
        self.lines = sorted(lines, key=lambda line: line.start)
        self._starts = [line.start for line in self.lines]
        self.language = language

    def __len__(self) -> int:
        return len(self.lines)

    def index_at(self, moment: float) -> int:
        """The line playing at `moment`, or -1 between lines."""
        index = bisect.bisect_right(self._starts, moment) - 1
        if index >= 0 and moment <= self.lines[index].end:
            return index
        return -1

    def at(self, moment: float) -> Line | None:
        index = self.index_at(moment)
        return self.lines[index] if index >= 0 else None

    def next_from(self, moment: float) -> int:
        """The first line starting at or after `moment` (len when none)."""
        return bisect.bisect_left(self._starts, moment)


_SENTENCE_END = re.compile(r"[.!?…]['\"»”’)\]]*\s*$")

#: A pause this long ends a sentence for the voice even without a full stop.
SENTENCE_PAUSE = 1.5
#: Nor is a spoken sentence allowed to run longer than this.
SENTENCE_SPAN = 25.0


def speech_lines(track: Track) -> list[Line]:
    """The track's lines joined back into the sentences they were cut from.

    A subtitle line is cut to fit the screen, often mid-sentence, and a
    voice given one on its own reads it as a finished sentence: the pitch
    falls on its last word. Heard on a Langfuse talk -- «…или нуждаетесь в
    более» | «эффективной совместной работе…» came out as two sentences,
    the first ending on «более». The screen keeps its lines; the voice gets
    the sentence, from its first line's start to its last line's end.
    """
    joined: list[Line] = []
    group: list[Line] = []

    def close() -> None:
        if group:
            joined.append(Line(
                group[0].start, group[-1].end,
                " ".join(line.original for line in group if line.original),
                " ".join(line.translated for line in group if line.translated),
                group[0].voice,
            ))
            group.clear()

    for line in track.lines:
        if group and (
            line.start - group[-1].end > SENTENCE_PAUSE
            or line.end - group[0].start > SENTENCE_SPAN
            # Another person answering is another sentence, whatever the
            # punctuation says.
            or line.voice != group[-1].voice
        ):
            close()
        group.append(line)
        if _SENTENCE_END.search(line.translated):
            close()
    close()
    return joined


def track_from_result(result) -> Track:
    """The file pipeline's translated cues, paired with their originals."""
    from lt_core.subtitles.bilingual import fold_original

    translated = tuple(result.translated_cues or ())
    original = tuple(result.cues)
    if translated and len(original) != len(translated):
        original = fold_original(original, translated)
    lines = []
    for index, cue in enumerate(translated or original):
        source = original[index].flat_text if index < len(original) else ""
        lines.append(Line(cue.start, cue.end, source.strip(), cue.flat_text.strip()))
    return Track(lines, language=result.transcript.language)


def cast_track(track: Track, audio, rate: int, model=None) -> tuple[Track, object]:
    """Each line marked male or female, for a voice of the same register.

    With a speaker model the people are told apart by their voices first
    and each person gets one register (`lt_core.tts.speakers`); without one,
    the file dub's per-line pitch casting, which keeps one voice for the
    video unless the registers are clearly apart.
    """
    from lt_core.tts import casting

    cues = tuple(track.lines)
    if model is not None:
        from lt_core.tts import speakers

        people = speakers.speaker_of(speakers.identify(cues, audio, rate, model), cues)
        cast = casting.cast_people(cues, audio, rate, people)
    else:
        cast = casting.analyse(cues, audio, rate)
    lines = [replace(line, voice=gender)
             for line, gender in zip(track.lines, cast.genders)]
    return Track(lines, language=track.language), cast


class AheadWorker(QThread):
    """Fetch a video's sound and run it through the file pipeline."""

    stage = Signal(str)
    done = Signal(object)  # Track
    failed = Signal(str)

    def __init__(self, url: str, folder: Path, transcriber, translator,
                 source_language: str | None, target_language: str,
                 parent: QObject | None = None, match_voices: bool = False,
                 speaker_dir: Path | None = None) -> None:
        super().__init__(parent)
        self.url = url
        self.folder = folder
        self.transcriber = transcriber
        self.translator = translator
        self.source_language = source_language
        self.target_language = target_language
        #: Measure who speaks each line, so a woman is read by a woman.
        self.match_voices = match_voices
        #: Where the speaker model is kept (fetched there on first use).
        self.speaker_dir = speaker_dir
        #: The casting, once made (`casting.Cast`), for the status line.
        self.cast = None
        self._cancelled = False

    def cancel(self) -> None:
        """Results arriving after this are thrown away."""
        self._cancelled = True

    def run(self) -> None:
        from lt_core.asr.transcriber import TranscribeOptions
        from lt_core.pipeline.batch import transcribe_file

        try:
            result = transcribe_file(
                self.url,
                self.transcriber,
                output_dir=self.folder,
                formats=("srt",),
                options=TranscribeOptions(language=self.source_language),
                on_stage=self.stage.emit,
                download_dir=self.folder,
                translator=self.translator,
                target_language=self.target_language,
                bilingual=True,
                voice=False,
            )
        except Exception as error:  # noqa: BLE001 -- surface anything
            if not self._cancelled:
                self.failed.emit(str(error))
            return
        track = track_from_result(result)
        if self.match_voices and len(track) and not self._cancelled:
            from lt_core.tts.dub import _load

            rate = 16_000
            audio = _load(result.media.path, rate)
            model = None
            if self.speaker_dir is not None:
                from lt_core.tts import speakers

                try:
                    model = speakers.ensure_model(self.speaker_dir)
                except Exception:  # noqa: BLE001 -- offline: pitch alone will do
                    model = None
            self.stage.emit(say("Различаю голоса"))
            try:
                track, self.cast = cast_track(track, audio, rate, model)
            except Exception:  # noqa: BLE001 -- the speaker model failed: pitch alone
                try:
                    track, self.cast = cast_track(track, audio, rate)
                except Exception:  # noqa: BLE001 -- one voice is still a translation
                    self.cast = None
        if not self._cancelled:
            self.done.emit(track)


class CueVoice:
    """Speak each line at its own moment on the video's clock.

    `clock()` returns (seconds into the video, playing). A line is spoken
    when the clock reaches its start. A late one -- the sentence before ran
    long, as Russian after English does -- is still read while its moment in
    the video lasts; one the clock has run past (a seek, or a sentence before
    it that ran over all of it) is skipped rather than read over whatever is
    being said by then. The next few lines are synthesised ahead, fitted to
    their slot, so a line starts on time.

    `synth(line) -> (samples, rate)` and `play(samples, rate)` are injected;
    `announce(bool)` is told as a line starts and ends (the page ducks).
    """

    LATE = 1.5
    AHEAD = 3
    TICK = 0.03

    def __init__(self, track: Track, clock: Callable[[], tuple[float, bool]],
                 synth, play, announce=None) -> None:
        self.track = track
        self.clock = clock
        self.synth = synth
        self.play = play
        self.announce = announce
        self.spoken = 0
        self.skipped = 0
        self._stop = threading.Event()
        self._cache: dict[int, tuple] = {}
        self._wanted: queue.Queue[int | None] = queue.Queue()
        self._requested: set[int] = set()
        self._lock = threading.Lock()
        self._maker = threading.Thread(target=self._make, name="CueSynth", daemon=True)
        self._speaker = threading.Thread(target=self._speak_loop, name="CueVoice", daemon=True)

    def start(self) -> None:
        self._maker.start()
        self._speaker.start()

    def stop(self) -> None:
        self._stop.set()
        self._wanted.put(None)

    def join(self, timeout: float = 5.0) -> None:
        self._maker.join(timeout)
        self._speaker.join(timeout)

    # -- synthesis ahead ---------------------------------------------------
    def _request(self, index: int) -> None:
        with self._lock:
            if index in self._requested or index >= len(self.track):
                return
            self._requested.add(index)
        self._wanted.put(index)

    def _make(self) -> None:
        while not self._stop.is_set():
            index = self._wanted.get()
            if index is None:
                return
            try:
                made = self.synth(self.track.lines[index])
            except Exception:  # noqa: BLE001 -- a line that fails is a line unheard
                made = None
            with self._lock:
                self._cache[index] = made

    def _take(self, index: int, wait: float):
        """The synthesised line, waiting up to `wait` seconds for it."""
        self._request(index)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and not self._stop.is_set():
            with self._lock:
                if index in self._cache:
                    return self._cache.pop(index)
            time.sleep(0.01)
        return None

    # -- speaking on the clock ---------------------------------------------
    def _speak_loop(self) -> None:
        index = None
        while not self._stop.is_set():
            moment, playing = self.clock()
            if index is None or not self._near(index, moment):
                # First run, or the clock jumped (a seek): start from here.
                index = self._first_unpassed(moment)
                with self._lock:
                    self._cache = {k: v for k, v in self._cache.items() if k >= index}
                    self._requested = {k for k in self._requested if k >= index}
            for ahead in range(index, min(index + self.AHEAD, len(self.track))):
                self._request(ahead)
            if index >= len(self.track):
                time.sleep(self.TICK * 5)
                continue
            line = self.track.lines[index]
            if not playing or moment < line.start:
                time.sleep(self.TICK)
                continue
            if self._passed(line, moment):
                # What is left of its moment in the video is not enough to
                # say it in: a seek went past it, or the sentence before ran
                # long over all of it.
                self.skipped += 1
                index += 1
                continue
            made = self._take(index, wait=self.LATE)
            index += 1
            if made is None:
                continue
            samples, rate = made
            if self.announce is not None:
                self.announce(True)
            try:
                self.play(samples, rate)
                self.spoken += 1
            finally:
                if self.announce is not None:
                    self.announce(False)

    def _passed(self, line: Line, moment: float) -> bool:
        """Too little of the line's moment left in the video to say it in."""
        return moment > max(line.start + self.LATE, line.end - self.LATE)

    def _first_unpassed(self, moment: float) -> int:
        """Where to start reading at `moment`: the first line not yet passed,
        one already under way included."""
        index = self.track.next_from(moment - 60.0)
        while index < len(self.track) and self._passed(self.track.lines[index], moment):
            index += 1
        return index

    def _near(self, index: int, moment: float) -> bool:
        """Whether `index` is still the right place for `moment`."""
        lines = self.track.lines
        if index < len(lines) and moment < lines[index].start - 5.0:
            return False  # jumped back
        if index > 0 and moment < lines[index - 1].start - self.LATE:
            return False  # jumped back past the last line
        if index < len(lines) and moment > lines[index].end + 5.0:
            return False  # jumped forward
        return True
