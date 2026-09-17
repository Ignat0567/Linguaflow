"""File-mode command line.

    python tools/transcribe.py video.mp4
    python tools/transcribe.py talk.mp3 --language de --format srt vtt json
    python tools/transcribe.py https://... --out ./subs

Prints a live progress bar driven by the segments the model actually emits, so
the percentage means something rather than being interpolated from a guess.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lt_core.asr.transcriber import (  # noqa: E402
    SUPPORTED_LANGUAGES,
    Transcriber,
    TranscribeOptions,
    UnsupportedLanguage,
)
from lt_core.media import MediaError, resolve  # noqa: E402
from lt_core.mt.translator import build_translator  # noqa: E402
from lt_core.mt.types import TranslationError, TranslationMode  # noqa: E402
from lt_core.pipeline.batch import transcribe_file  # noqa: E402
from lt_core.subtitles.export import EXPORTERS, format_srt_time  # noqa: E402

MODEL_ROOT = Path(__file__).resolve().parent.parent / "models"


def _bar(done: float, total: float, width: int = 28) -> str:
    fraction = min(1.0, done / total) if total else 0.0
    filled = int(fraction * width)
    return f"[{'#' * filled}{'.' * (width - filled)}] {fraction * 100:5.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Распознавание речи в файле или по ссылке")
    parser.add_argument("source", help="путь к медиафайлу или URL")
    parser.add_argument(
        "--language", "-l", choices=sorted(SUPPORTED_LANGUAGES),
        help="язык речи; по умолчанию определяется автоматически")
    parser.add_argument(
        "--format", "-f", nargs="+", default=["srt", "txt"],
        choices=sorted(EXPORTERS), metavar="FORMAT",
        help=f"форматы вывода ({', '.join(sorted(EXPORTERS))})")
    parser.add_argument("--out", "-o", help="папка для результатов")
    parser.add_argument("--model", help="имя или путь модели Whisper")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument(
        "--no-vad", action="store_true",
        help="не отфильтровывать тишину перед распознаванием")

    translation = parser.add_argument_group("перевод")
    translation.add_argument(
        "--to", "-t", choices=sorted(SUPPORTED_LANGUAGES), metavar="LANG",
        help="язык перевода; без него выполняется только расшифровка")
    translation.add_argument(
        "--mode", choices=[TranslationMode.OFFLINE, TranslationMode.ONLINE],
        default=TranslationMode.OFFLINE,
        help="offline — ничего не покидает компьютер (по умолчанию); "
             "online — текст уходит во внешний сервис")
    translation.add_argument(
        "--service", default="deepl", choices=["deepl", "openai"],
        help="сервис для онлайн-режима")
    translation.add_argument("--api-key", help="ключ доступа для онлайн-режима")
    translation.add_argument("--glossary", help="CSV или JSON с терминами")
    translation.add_argument(
        "--bilingual", action="store_true",
        help="дополнительный SRT с обоими языками")
    args = parser.parse_args()

    # Resolve the source before loading the model. Loading costs a couple of
    # seconds and a couple of gigabytes of VRAM, and spending them to then
    # announce that a URL was mistyped is a poor trade.
    download_dir = MODEL_ROOT.parent / "downloads"
    try:
        media = resolve(args.source, download_dir)
    except MediaError as error:
        print(str(error))
        if error.detail:
            print("\nПодробности:")
            print(f"  {error.detail}")
        return 1
    if not media.has_audio:
        print(f"В «{media.path.name}» нет звуковой дорожки.")
        return 2

    # Build the translator before the long transcription, not after it. A
    # missing API key or an unreadable glossary should surface in a second,
    # not once the GPU has finished ten minutes of work.
    translator = None
    if args.to:
        options = {"api_key": args.api_key} if args.api_key else {}
        if args.mode == TranslationMode.ONLINE:
            options["service"] = args.service
        try:
            translator = build_translator(
                args.mode, glossary_path=args.glossary,
                model_root=MODEL_ROOT, **options,
            )
        except (TranslationError, FileNotFoundError) as error:
            print(str(error))
            detail = getattr(error, "detail", "")
            if detail:
                print("\nПодробности:")
                print(f"  {detail}")
            return 1

    started = time.perf_counter()
    print("Модель загружается...", end="", flush=True)
    try:
        transcriber = Transcriber(
            model=args.model or Transcriber.__init__.__defaults__[0],
            device=args.device,
            model_root=MODEL_ROOT,
        )
    except Exception as error:
        print(f"\rНе удалось загрузить модель: {error}")
        return 1
    print(f"\rМодель: {transcriber.model_name.split('/')[-1]} "
          f"на {transcriber.device} ({transcriber.compute_type}), "
          f"{time.perf_counter() - started:.1f} с")

    state = {"last": 0.0}

    def on_progress(done: float, total: float) -> None:
        now = time.perf_counter()
        if now - state["last"] < 0.15 and done < total:
            return
        state["last"] = now
        print(f"\r  {_bar(done, total)}  {done:6.0f} / {total:.0f} с", end="",
              flush=True)

    try:
        result = transcribe_file(
            media.path,
            transcriber,
            output_dir=args.out,
            formats=tuple(args.format),
            options=TranscribeOptions(
                language=args.language, vad_filter=not args.no_vad
            ),
            on_stage=lambda message: print(f"\n{message}...", end="", flush=True),
            on_progress=on_progress,
            download_dir=download_dir,
            translator=translator,
            target_language=args.to,
            bilingual=args.bilingual,
        )
    except UnsupportedLanguage as error:
        print(f"\n{error}")
        return 2
    except MediaError as error:
        print(f"\n{error}")
        if error.detail:
            print(f"\nПодробности:\n  {error.detail}")
        return 1
    except ValueError as error:
        print(f"\n{error}")
        return 2
    except KeyboardInterrupt:
        print("\nПрервано.")
        return 130

    transcript = result.transcript
    print("\n")
    print(f"Источник:   {result.media.title}  "
          f"({format_srt_time(result.media.duration)[:-4]})")
    print(f"Язык:       {result.language_name} "
          f"(уверенность {transcript.language_probability:.0%})")
    if not result.is_supported_language:
        print("            ВНИМАНИЕ: язык вне восьми поддерживаемых — "
              "качество не гарантировано.")
    print(f"Скорость:   {transcript.elapsed:.1f} с на "
          f"{transcript.duration:.0f} с аудио "
          f"(в {1 / transcript.realtime_factor:.0f} раз быстрее реального времени)")
    print(f"Результат:  {len(transcript.segments)} сегментов, "
          f"{len(transcript.words)} слов, {len(result.cues)} субтитров")

    fast = result.fast_cues
    if fast:
        print(f"Темп:       {len(fast)} субтитров быстрее нормы чтения "
              f"(диктор говорит быстро; текст не сокращался)")

    report = result.translation
    if report is not None:
        where = "офлайн, ничего не покидало компьютер" if report.offline else (
            "ОНЛАЙН, текст отправлялся во внешний сервис")
        print(f"Перевод:    {report.provider} -- {where}")
        print(f"            {report.summary()}")
        if report.number_mismatches:
            print()
            print(f"  ЧИСЛА РАСХОДЯТСЯ в {len(report.number_mismatches)} "
                  f"фрагментах -- проверьте вручную:")
            for mismatch in report.number_mismatches[:5]:
                stamp = format_srt_time(result.locate(mismatch.index))[:-4]
                print(f"    {stamp}: {mismatch.describe()}")
                print(f"      было:  {mismatch.source[:70]}")
                print(f"      стало: {mismatch.target[:70]}")
            if len(report.number_mismatches) > 5:
                print(f"    ... и ещё {len(report.number_mismatches) - 5}")
        if report.risky_short:
            print()
            print(f"  {len(report.risky_short)} фрагментов короче трёх слов — "
                  f"локальная модель на таких ненадёжна")
            print(f"    (для реплик вроде «Да» или «Здравствуйте» "
                  f"проверьте перевод вручную)")

    print()
    for name, path in result.outputs.items():
        print(f"  {name:5s} -> {path}")
    print(f"\nВсего {result.elapsed:.1f} с.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
