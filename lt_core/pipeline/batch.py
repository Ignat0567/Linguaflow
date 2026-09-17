"""File mode: media in, transcript and subtitles out.

One function that a CLI or a UI can both call, reporting progress as it goes
and returning everything either of them might want to show.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..asr.transcriber import SUPPORTED_LANGUAGES, Transcriber, TranscribeOptions
from ..asr.types import Transcript
from ..media import MediaInfo, resolve
from ..subtitles.cues import Cue, CueStyle, build_cues
from ..subtitles.export import EXPORTERS, write

DEFAULT_FORMATS = ("srt", "txt")


@dataclass
class BatchResult:
    media: MediaInfo
    transcript: Transcript
    cues: tuple[Cue, ...]
    outputs: dict[str, Path] = field(default_factory=dict)
    elapsed: float = 0.0

    @property
    def language_name(self) -> str:
        return SUPPORTED_LANGUAGES.get(self.transcript.language,
                                       self.transcript.language)

    @property
    def is_supported_language(self) -> bool:
        return self.transcript.language in SUPPORTED_LANGUAGES

    @property
    def fast_cues(self) -> tuple[Cue, ...]:
        """Cues that stay on screen too briefly for their length.

        Not an error -- a fast speaker produces them unavoidably, since the
        alternative is condensing what they said. Worth reporting rather than
        hiding.
        """
        style = CueStyle.for_language(self.transcript.language)
        return tuple(c for c in self.cues if c.chars_per_second > style.max_cps * 1.05)


def transcribe_file(
    target: str | Path,
    transcriber: Transcriber,
    output_dir: Path | str | None = None,
    formats: tuple[str, ...] = DEFAULT_FORMATS,
    options: TranscribeOptions | None = None,
    style: CueStyle | None = None,
    on_stage: Callable[[str], None] | None = None,
    on_progress: Callable[[float, float], None] | None = None,
    download_dir: Path | str | None = None,
) -> BatchResult:
    """Transcribe a file or URL and write the requested formats."""
    started = time.perf_counter()

    def stage(message: str) -> None:
        if on_stage is not None:
            on_stage(message)

    unknown = [name for name in formats if name not in EXPORTERS]
    if unknown:
        raise ValueError(
            f"Неизвестный формат: {', '.join(unknown)}. "
            f"Доступны: {', '.join(EXPORTERS)}"
        )

    scratch = Path(download_dir) if download_dir else Path.cwd() / "downloads"
    stage("Открываю источник")
    media = resolve(str(target), scratch)
    if not media.has_audio:
        raise ValueError(f"В «{media.path.name}» нет звуковой дорожки.")

    stage(f"Распознаю ({media.duration / 60:.1f} мин)")
    transcript = transcriber.transcribe(
        media.path,
        options=options,
        on_progress=on_progress,
        total_duration=media.duration or None,
    )

    # The model's last segment rarely ends exactly at the file's end, so the
    # bar would otherwise freeze short of 100% and look stalled.
    if on_progress is not None and media.duration:
        on_progress(media.duration, media.duration)

    stage("Собираю субтитры")
    cues = build_cues(transcript, style)

    destination = Path(output_dir) if output_dir else media.path.parent
    outputs: dict[str, Path] = {}
    for name in formats:
        content = EXPORTERS[name](transcript, cues)
        outputs[name] = write(destination / f"{media.path.stem}.{name}", content)

    return BatchResult(
        media=media,
        transcript=transcript,
        cues=cues,
        outputs=outputs,
        elapsed=time.perf_counter() - started,
    )
