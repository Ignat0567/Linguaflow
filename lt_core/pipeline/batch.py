"""File mode: media in, transcript and subtitles out.

One function that a CLI or a UI can both call, reporting progress as it goes
and returning everything either of them might want to show.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import languages
from ..asr.transcriber import Transcriber, TranscribeOptions
from ..asr.types import Transcript
from ..media import MediaInfo, resolve
from ..mt.translator import TranslationReport, Translator
from ..subtitles.bilingual import (
    distribute,
    group_into_sentences,
    merge_bilingual,
    translate_cues,
)
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
    # Present only when a translation was requested.
    translated_cues: tuple[Cue, ...] | None = None
    translation: TranslationReport | None = None
    target_language: str | None = None
    #: The dubbed track, when one was asked for.
    dub: object | None = None
    # Which cues each translated sentence covered, so a flagged sentence can be
    # reported at the time it was spoken rather than as an index nobody can
    # locate in a subtitle file.
    sentence_groups: list[list[int]] = field(default_factory=list)

    @property
    def language_name(self) -> str:
        # Named from the whole catalogue, not from what this build offers: a
        # French recording should be reported as French, with a note that it is
        # outside what has been measured, rather than as the bare code "fr".
        return languages.describe(self.transcript.language)

    @property
    def is_supported_language(self) -> bool:
        return languages.is_active(self.transcript.language)

    def locate(self, sentence_index: int) -> float:
        """When the given translated sentence starts, in seconds."""
        if 0 <= sentence_index < len(self.sentence_groups):
            first = self.sentence_groups[sentence_index][0]
            if 0 <= first < len(self.cues):
                return self.cues[first].start
        return 0.0

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
    translator: Translator | None = None,
    target_language: str | None = None,
    bilingual: bool = False,
    voice: bool = False,
    keep_original_audio: bool = True,
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

    translated_cues = None
    report = None
    if translator is not None and target_language:
        stage(f"Перевожу на {languages.describe(target_language)}")
        # Whole sentences, not cues. A cue is cut for reading speed and is
        # often a fragment, and a fragment is what makes this model invent.
        groups = group_into_sentences(cues)
        joiner = " " if languages.joins_with_space(transcript.language) else ""
        sentences = [
            joiner.join(cues[position].flat_text for position in group)
            for group in groups
        ]
        sentence_translations, report = translator.translate(
            sentences, transcript.language, target_language
        )

        target_joins_with_space = languages.joins_with_space(target_language)
        translations: list[str] = [""] * len(cues)
        for group, translated in zip(groups, sentence_translations):
            shares = distribute(
                translated,
                [len(cues[position].flat_text) for position in group],
                join_with_space=target_joins_with_space,
            )
            for position, share in zip(group, shares):
                translations[position] = share
        # Timings belong to the speech and do not move: only the words change.
        translated_cues = translate_cues(
            cues, translations, CueStyle.for_language(target_language)
        )
        for name in formats:
            if name not in ("srt", "vtt"):
                continue
            stem = f"{media.path.stem}.{target_language}"
            outputs[f"{name}.{target_language}"] = write(
                destination / f"{stem}.{name}",
                EXPORTERS[name](transcript, translated_cues),
            )
        if bilingual:
            merged = merge_bilingual(cues, translated_cues)
            outputs["srt.bilingual"] = write(
                destination / f"{media.path.stem}.{transcript.language}-{target_language}.srt",
                EXPORTERS["srt"](transcript, merged),
            )

    dub = None
    if voice and translated_cues:
        from ..tts.dub import mix
        from ..tts.speaker import Speaker, write_wav

        stage("Озвучиваю перевод")
        speaker = Speaker(target_language,
                          voices_dir=Path(__file__).resolve().parents[2] / "models" / "piper")
        dub = mix(media.path, translated_cues, speaker, media.duration,
                  keep_original=keep_original_audio)
        outputs["audio"] = write_wav(
            destination / f"{media.path.stem}.{target_language}.wav",
            dub.samples, dub.rate,
        )

    return BatchResult(
        media=media,
        transcript=transcript,
        cues=cues,
        outputs=outputs,
        elapsed=time.perf_counter() - started,
        translated_cues=translated_cues,
        translation=report,
        target_language=target_language,
        sentence_groups=groups if translator is not None and target_language else [],
        dub=dub,
    )
