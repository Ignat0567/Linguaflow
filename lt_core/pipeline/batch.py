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
from ..messages import say as tell
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

#: How much faster than its natural pace the voice may be asked to speak when
#: deciding how much text fits. Measured on Day 5: past about 18% the voice
#: stops sounding like a person, so the text budget is allowed to count on
#: that much and no more.
SPEED_HEADROOM = 1.18


def _named(code: str) -> str:
    """The language's name, capitalised, then through the message seam.

    `describe` returns Russian in lowercase, which is right for a log and
    wrong as a caption in a German window. Capitalising matches the
    interface catalogue («Русский»), so the installed translator can
    replace it.
    """
    name = languages.describe(code)
    pretty = name[:1].upper() + name[1:] if name else code
    return tell(pretty)


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
    #: What shortening did to each line, when it was asked for.
    condensed: list = field(default_factory=list)
    #: What the model was asked to shorten, and what survived the checks.
    shorten_report: object | None = None

    @property
    def shortened(self) -> list:
        return [record for record in self.condensed if record.changed]
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


def _spread(cues, groups, sentences, language: str, with_space: bool):
    """Put each translated sentence back across the cues it came from.

    Subtitles are cut for reading speed, so a sentence routinely spans two or
    three of them and its translation has to be divided the same way. The
    timings never move; only the words change.
    """
    translations: list[str] = [""] * len(cues)
    for group, translated in zip(groups, sentences):
        shares = distribute(
            translated,
            [len(cues[position].flat_text) for position in group],
            join_with_space=with_space,
        )
        for position, share in zip(group, shares):
            translations[position] = share
    return translate_cues(cues, translations, CueStyle.for_language(language))


def _sentence_cues(cues, groups, sentences) -> tuple[Cue, ...]:
    """The translation as whole sentences, with the time each one has.

    A dub built from subtitle cues speaks in fragments, because a subtitle is
    cut where a line gets too long to read and not where a thought ends.
    Measured on a real recording: 117 of 519 spoken lines ended mid-clause --
    «Часто люди думают, что я» and then, after a pause, «делаю это». Nobody
    talks like that, and on a recording there is no reason to: the whole
    sentence is known before a word of it is spoken.

    Each sentence starts where its first cue starts and has the time until
    the next sentence begins -- including the silence between them, which is
    time nothing else is using.
    """
    units: list[Cue] = []
    for index, (group, text) in enumerate(zip(groups, sentences)):
        if not group or not text.strip():
            continue
        start = cues[group[0]].start
        if index + 1 < len(groups) and groups[index + 1]:
            end = cues[groups[index + 1][0]].start
        else:
            end = cues[group[-1]].end
        units.append(
            Cue(index=len(units) + 1, start=start, end=max(end, start + 0.05),
                lines=(text.strip(),))
        )
    return tuple(units)


def _write_translated(
    outputs, formats, destination, media, transcript, cues, translated_cues,
    target_language: str, bilingual: bool,
) -> None:
    """Write the translated subtitle files.

    Called before the video is assembled, because the assembler embeds one of
    them as a track. Moving this to the end once cost exactly that: the video
    came out with both soundtracks and no subtitles, and nothing said so.
    """
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
            destination
            / f"{media.path.stem}.{transcript.language}-{target_language}.srt",
            EXPORTERS["srt"](transcript, merged),
        )


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
    match_voices: bool = True,
    dub_video: bool = True,
    condense: bool = True,
    shortener: object | None = None,
    cookies: Path | str | None = None,
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
    stage(tell("Открываю источник"))
    # A dubbed copy needs the picture, and for a link that means downloading
    # it. Asked for, it is fetched; not asked for, only the audio comes down.
    media = resolve(
        str(target), scratch, want_video=bool(voice and dub_video), cookies=cookies
    )
    if not media.has_audio:
        raise ValueError(f"В «{media.path.name}» нет звуковой дорожки.")

    stage(tell("Распознаю ({minutes} мин)", minutes=f"{media.duration / 60:.1f}"))
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

    stage(tell("Собираю субтитры"))
    cues = build_cues(transcript, style)

    destination = Path(output_dir) if output_dir else media.path.parent
    outputs: dict[str, Path] = {}
    for name in formats:
        content = EXPORTERS[name](transcript, cues)
        outputs[name] = write(destination / f"{media.path.stem}.{name}", content)

    translated_cues = None
    report = None
    sentence_groups: list[list[int]] = []
    spoken_units: tuple[Cue, ...] = ()
    if translator is not None and target_language and transcript.language == target_language:
        # Auto-detect can land on the language the user asked to translate
        # into. Translating a language into itself is a hard error downstream,
        # and the original subtitles are already the right file.
        stage(tell("Язык оригинала совпал с языком перевода"))
    elif translator is not None and target_language:
        stage(tell(
            "Перевожу на {language}",
            language=_named(target_language),
        ))
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
        translated_cues = _spread(
            cues, groups, sentence_translations, target_language,
            target_joins_with_space,
        )
        # Kept whole as well as spread: subtitles are cut for reading speed,
        # and speech is not. See `_sentence_cues`.
        spoken_units = _sentence_cues(cues, groups, sentence_translations)
        sentence_groups = groups
        if not voice:
            # With a dub the text may still be shortened, so the files are
            # written after that instead; without one it is already final.
            _write_translated(
                outputs, formats, destination, media, transcript, cues,
                translated_cues, target_language, bilingual,
            )

    dub = None
    condensed: list = []
    shorten_report = None
    if voice and translated_cues:
        from ..mt.condense import condense_cues
        from ..mt.shorten_with_model import can_shorten, shorten_cues
        from ..tts.dub import mix
        from ..tts.speaker import VoiceBank, write_wav

        voices_dir = Path(__file__).resolve().parents[2] / "models" / "piper"
        pair = match_voices and languages.has_voice_pair(target_language)
        bank = VoiceBank(target_language, voices_dir=voices_dir,
                         single=languages.voice_for(target_language))

        if condense:
            # Before the subtitles are written, so that what is read out and
            # what is on screen are the same sentence. The budget comes from
            # the voice that will actually speak, whose pace is measured
            # rather than assumed.
            stage(tell("Сокращаю перевод под тайминг"))
            pace, overhead = bank.for_gender().pace()

            def measure(text: str, _bank=bank) -> float:
                """How long this voice really takes over this text."""
                samples, rate = _bank.for_gender().say(text)
                return len(samples) / rate if rate else 0.0
            # Whole sentences, not subtitle cues: a sentence has the time of
            # all its cues together, so there is more room to fit into and
            # more context to shorten within.
            spoken_units, condensed = condense_cues(
                spoken_units, target_language, pace,
                headroom=SPEED_HEADROOM, overhead=overhead, measure=measure,
            )
            # The rules remove filler, and a machine translation has little.
            # Whatever still does not fit is rewritten by a model.
            #
            # Which model is a separate choice from which translator, and the
            # measurements are why. Translating this recording through a
            # 31-billion-parameter model on a free tier would have taken about
            # twenty minutes at 3-5 seconds a line, where the local model does
            # it in four seconds and does it well. Only the lines that do not
            # fit need rewriting -- 101 of 243 here -- so only those need to
            # leave, and the translation can stay on this machine.
            rewriter = shortener
            if rewriter is None and translator is not None:
                if can_shorten(translator.provider):
                    rewriter = translator.provider
            if rewriter is not None and can_shorten(rewriter):
                stage(tell("Сокращаю остальное моделью"))
                spoken_units, condensed, shorten_report = shorten_cues(
                    spoken_units, target_language, pace, rewriter,
                    headroom=SPEED_HEADROOM, overhead=overhead,
                    measure=measure, records=condensed,
                )
                if shorten_report.summary():
                    stage(shorten_report.summary())

        if condense and spoken_units:
            # Shortening changed the sentences; the subtitles must say what is
            # said, so they are rebuilt from the sentences rather than kept
            # from before.
            translated_cues = _spread(
                cues, sentence_groups,
                [unit.flat_text for unit in spoken_units],
                target_language, languages.joins_with_space(target_language),
            )

        _write_translated(
            outputs, formats, destination, media, transcript, cues,
            translated_cues, target_language, bilingual,
        )

        speaker_model = None
        if pair:
            # Told apart by voice, not by pitch alone; fetched on first use,
            # and without it (offline) the pitch casting still runs.
            from ..tts import speakers

            try:
                speaker_model = speakers.ensure_model(voices_dir.parent / "speaker")
                stage(tell("Различаю голоса"))
            except Exception:  # noqa: BLE001
                speaker_model = None
        stage(tell("Озвучиваю перевод, голоса по говорящему") if pair
              else tell("Озвучиваю перевод"))
        # Spoken as sentences. A dub cut to subtitle timings speaks in
        # fragments, because a subtitle ends where a line gets too long to
        # read and not where a thought ends.
        dub = mix(media.path, spoken_units or translated_cues, bank,
                  media.duration, keep_original=keep_original_audio,
                  match_voices=pair, speaker_model=speaker_model)
        outputs["audio"] = write_wav(
            destination / f"{media.path.stem}.{target_language}.wav",
            dub.samples, dub.rate,
        )
        if dub.cast is not None:
            stage(dub.cast.summary())

        if dub_video and media.has_video:
            from ..video.mux import MuxError, replace_audio

            stage(tell("Собираю видео с переводом"))
            try:
                muxed = replace_audio(
                    media.path,
                    outputs["audio"],
                    destination / f"{media.path.stem}.{target_language}",
                    target_language=target_language,
                    source_language=transcript.language,
                    subtitles=outputs.get(f"srt.{target_language}"),
                    keep_original=True,
                    duration=media.duration,
                )
            except MuxError as exc:
                # The soundtrack is already written and useful on its own; a
                # container that would not take it is worth reporting, not
                # worth losing the job over.
                stage(tell("Видео собрать не удалось: {reason}", reason=str(exc)))
            else:
                outputs["video"] = muxed.path

    return BatchResult(
        media=media,
        transcript=transcript,
        cues=cues,
        outputs=outputs,
        elapsed=time.perf_counter() - started,
        translated_cues=translated_cues,
        translation=report,
        target_language=target_language,
        sentence_groups=sentence_groups,
        dub=dub,
        condensed=condensed,
        shorten_report=shorten_report,
    )
