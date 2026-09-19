"""Speech recognition via faster-whisper.

Holds the model, feeds it audio, and returns a Transcript. Everything about
subtitle shape belongs downstream; this layer's job is to be accurate about
what was said and when.

Measured on the project machine (RTX 3050, large-v3-turbo, int8_float16):
a real-time factor around 0.04, so an hour of audio takes about two and a half
minutes. Compute is not the constraint here.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import languages
from ..runtime import bootstrap
from .types import Segment, Transcript, Word

# Languages are declared in one place; see lt_core.languages for why, and for
# how to offer more of them.
SUPPORTED_LANGUAGES: dict[str, str] = languages.names()

DEFAULT_MODEL = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"


@dataclass(frozen=True)
class TranscribeOptions:
    """Knobs that change the transcript rather than its presentation."""

    language: str | None = None          # None means detect
    beam_size: int = 5
    # Whisper invents text over silence and music. faster-whisper's VAD filter
    # removes the silence before the model ever sees it, which is a far more
    # effective cure than filtering the output afterwards.
    vad_filter: bool = True
    word_timestamps: bool = True
    # Segments scoring below this are discarded as hallucinations. -1.0 is
    # conservative: real speech, even accented or noisy, rarely falls this low.
    min_avg_logprob: float = -1.0
    max_no_speech_probability: float = 0.6
    # Carry the previous window's text into the next as context.
    #
    # This was off, on the reasoning that one bad transcription poisons
    # everything after it. The reasoning is sound and the cost of leaving it
    # off turned out to be larger: without context the model punctuates the
    # first window and then gives up, and a transcript with no sentence ends
    # loses most of its translation further down the line. Measured on a
    # 12-minute recording: 23 sentence ends without it, 184 with it and a
    # punctuated sample to start from, the text itself 1.4% longer and no
    # repetition anywhere. Measured on two other recordings, both of which the
    # model already punctuated: -0.5% and +1.9% in length, no repetition.
    #
    # The poisoning risk is real and is bounded rather than dismissed:
    # faster-whisper's compression-ratio check and temperature fallback are on
    # by default, and `min_avg_logprob` still drops bad segments afterwards.
    #
    # The live path sets this back to False: there the previous text is a
    # two-second window, not a paragraph.
    condition_on_previous_text: bool = True
    #: Skip stretches of silence longer than this, in seconds, where the model
    #: would otherwise invent speech.
    #:
    #: Off, after measuring what it actually does. Aimed at the loops that
    #: conditioning can start, at 2.0 s it cut real speech instead: on a
    #: two-person recording it removed 111 characters of a genuine sentence --
    #: "released four major functions and significantly reduced the average
    #: response time" simply vanished between one clause and the next. A guard
    #: against silent loss that causes silent loss is not a guard. Available
    #: for a recording that needs it, and not the default.
    hallucination_silence_threshold: float | None = None
    initial_prompt: str | None = None
    #: Prime the model with a short, punctuated sample in the language being
    #: transcribed, so that it punctuates its own output.
    #:
    #: Without it, this model transcribes fast continuous speech as one
    #: unbroken run: measured on a real recording, one sentence end per 2227
    #: characters against thirteen with the sample. That matters far beyond
    #: readability -- the translator splits on sentence ends, and a transcript
    #: without any loses most of its translation.
    #:
    #: Ignored when `initial_prompt` is given, which stays the way to say
    #: something specific to one recording.
    punctuation_prompt: bool = True
    #: Discard segments that are only the credits this model invents over
    #: silence. See `_HALLUCINATIONS`.
    drop_hallucinations: bool = True


#: Text this model produces when what it is listening to is not speech.
#:
#: Whisper was trained on a corpus of subtitle files, credits and all, so given
#: silence or room noise it does not return nothing -- it returns the most
#: likely thing to appear in a subtitle file with no dialogue in it, which is
#: the translator's own credit. A user testing the microphone saw "Субтитры
#: сделал DimaTorzok" arrive as a turn, get routed to a speaker and translated
#: into "Subtitles made".
#:
#: File mode rarely shows it because the VAD filter removes silence before the
#: model sees any of it. The live path leaves that filter off deliberately --
#: on a two-second window it swallows a short word at the edge -- so silence
#: reaches the model directly, and this is where it is caught instead.
#:
#: Matched against the whole segment and nothing less. A line that merely
#: mentions subtitles is speech; a line that is only a credit is not.
#: A credit names somebody, and a name is capitalised. Requiring one is what
#: separates "Редактор субтитров А.Синецкая" from "Редактор субтитров
#: подготовил отчёт", and "Subtitles by Stephanie Geiges" from "Subtitles by
#: themselves are not enough". The case is checked case-sensitively inside an
#: otherwise case-insensitive pattern, which is what `(?-i:...)` is for.
_NAME = r"(?-i:[A-ZА-ЯЁÄÖÜ])"

_HALLUCINATIONS = tuple(re.compile(pattern, re.IGNORECASE | re.UNICODE) for pattern in (
    r"субтитры\s*(?:и\s*перевод\s*)?"
    r"(?:сделал|сделала|создавал|создал|делал|подготовил|выполнил|автор)\s+"
    + _NAME + r".*",
    r"(?:редактор|корректор)\s+субтитров\s+" + _NAME + r".*",
    r"(?:субтитр\w*|перевод)\s*[:\-–—]\s*" + _NAME + r".*",
    r"продолжение\s+следует\W*",
    r"спасибо\s+за\s+(?:просмотр|подписку)\W*",
    r"(?:подписывайтесь|подпишись|подпишитесь)\s+на\s+(?:наш\s+)?канал\W*",
    r"subtitles?\s+(?:by|created\s+by|made\s+by)\s+" + _NAME + r".*",
    r"thanks?\s*(?:you)?\s*for\s+watching\W*",
    r"please\s+(?:subscribe|like\s+and\s+subscribe)\W*",
    r"untertitel(?:ung)?\s+(?:von|im\s+auftrag|aufgrund|der)\s+" + _NAME + r".*",
    r"vielen\s+dank\s+f(?:ü|u)rs?\s+(?:zuschauen|zusehen)\W*",
    r".*\bamara\.org\b.*",
    r".*\bdimatorzok\b.*",
))


def is_hallucinated(text: str) -> bool:
    """Whether a segment is the model's idea of a subtitle file with no speech."""
    cleaned = re.sub(r"\s+", " ", text).strip().strip("\"'«»„“”")
    return any(pattern.fullmatch(cleaned) for pattern in _HALLUCINATIONS)


class UnsupportedLanguage(ValueError):
    pass


class Transcriber:
    """A loaded Whisper model.

    Loading costs about two seconds and a couple of gigabytes of VRAM, so one
    instance is meant to be kept and reused rather than created per file.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        device: str = "auto",
        compute_type: str | None = None,
        model_root: Path | str | None = None,
    ) -> None:
        bootstrap(model_root)
        from faster_whisper import WhisperModel

        self.model_name = model
        self.device, self.compute_type = _choose_device(device, compute_type)
        self._model = WhisperModel(
            model, device=self.device, compute_type=self.compute_type
        )

    # -- main entry point -------------------------------------------------
    def transcribe(
        self,
        audio: np.ndarray | str | Path,
        options: TranscribeOptions | None = None,
        on_progress: Callable[[float, float], None] | None = None,
        total_duration: float | None = None,
    ) -> Transcript:
        """Transcribe audio, reporting progress as segments are produced.

        `on_progress` receives (seconds_done, seconds_total). faster-whisper
        yields segments lazily, so progress is real rather than a guess -- but
        only if the caller knows the total, hence `total_duration` for arrays.
        """
        options = options or TranscribeOptions()
        if options.language and not languages.is_active(options.language):
            known = languages.get(options.language)
            extra = (
                f" Язык «{known.name}» есть в каталоге, но в этой сборке выключен."
                if known else ""
            )
            raise UnsupportedLanguage(
                f"Язык «{options.language}» не поддерживается. "
                f"Доступны: {languages.offered_list()}.{extra}"
            )

        source = str(Path(audio).resolve()) if isinstance(audio, (str, Path)) else audio
        started = time.perf_counter()

        language = options.language
        prompt = options.initial_prompt
        if prompt is None and options.punctuation_prompt:
            if language is None:
                # The sample has to be in the recording's own language, and a
                # prompt in the wrong one is the single way this is known to
                # cause harm -- so the language is settled first, off the
                # opening seconds, rather than guessed.
                language, _confidence = self.detect_language(source)
            prompt = languages.punctuation_sample(language) or None

        raw_segments, info = self._model.transcribe(
            source,
            language=language,
            beam_size=options.beam_size,
            vad_filter=options.vad_filter,
            word_timestamps=options.word_timestamps,
            condition_on_previous_text=options.condition_on_previous_text,
            initial_prompt=prompt,
            hallucination_silence_threshold=(
                options.hallucination_silence_threshold
                if options.word_timestamps else None
            ),
        )

        duration = total_duration if total_duration is not None else info.duration
        segments = tuple(
            self._collect(raw_segments, options, duration, on_progress)
        )
        return Transcript(
            segments=segments,
            language=info.language,
            language_probability=float(info.language_probability),
            duration=float(duration),
            elapsed=time.perf_counter() - started,
            model=self.model_name,
        )

    def detect_language(self, audio: np.ndarray | str | Path) -> tuple[str, float]:
        """Identify the language from the opening of the audio."""
        source = str(Path(audio).resolve()) if isinstance(audio, (str, Path)) else audio
        _, info = self._model.transcribe(source, beam_size=1, vad_filter=True)
        return info.language, float(info.language_probability)

    def detect_between(
        self, audio: np.ndarray, candidates: list[str]
    ) -> tuple[str, float, float]:
        """Choose the likeliest of a known set of languages.

        Asking "which of ninety-nine languages is this" from a two-second
        window is a much harder question than "which of these two", and it
        answers wrongly often enough to matter: in a conversation-mode run the
        German turn was identified as Russian, transcribed as Russian, and the
        translation of that came out as "The system." repeated five times.

        Returns the winner, its probability, and the margin over the runner-up.
        The margin is what a caller needs in order to require real evidence
        before switching speakers.
        """
        _, _, all_probabilities = self._model.detect_language(audio=audio)
        scores = {code: float(probability) for code, probability in all_probabilities}
        ranked = sorted(
            ((scores.get(code, 0.0), code) for code in candidates), reverse=True
        )
        if not ranked:
            return "", 0.0, 0.0
        best_score, best = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        return best, best_score, best_score - runner_up

    # -- internals --------------------------------------------------------
    def _collect(
        self,
        raw_segments: Iterable,
        options: TranscribeOptions,
        duration: float,
        on_progress: Callable[[float, float], None] | None,
    ):
        for raw in raw_segments:
            if on_progress is not None:
                on_progress(min(float(raw.end), duration), duration)

            text = raw.text.strip()
            if not text:
                continue
            if raw.avg_logprob < options.min_avg_logprob:
                continue
            if raw.no_speech_prob > options.max_no_speech_probability:
                continue
            if options.drop_hallucinations and is_hallucinated(text):
                continue

            words = tuple(
                Word(
                    text=word.word,
                    start=float(word.start),
                    end=float(word.end),
                    probability=float(getattr(word, "probability", 1.0)),
                )
                for word in (raw.words or [])
                if word.start is not None and word.end is not None
            )
            yield Segment(
                text=text,
                start=float(raw.start),
                end=float(raw.end),
                words=words,
                avg_logprob=float(raw.avg_logprob),
                no_speech_probability=float(raw.no_speech_prob),
            )


def _choose_device(device: str, compute_type: str | None) -> tuple[str, str]:
    """Pick CUDA when it is actually usable, CPU otherwise.

    `device="auto"` in CTranslate2 does not fall back gracefully when the GPU
    libraries are missing, so the decision is made here where a plain answer is
    available.
    """
    if device == "auto":
        try:
            import ctranslate2

            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"

    if compute_type is None:
        # int8_float16 halves VRAM against float16 at no measurable accuracy
        # cost here; on CPU, float16 is slower than int8, not faster.
        compute_type = "int8_float16" if device == "cuda" else "int8"
    return device, compute_type
