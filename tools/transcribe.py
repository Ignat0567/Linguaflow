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

    print()
    for name, path in result.outputs.items():
        print(f"  {name:5s} -> {path}")
    print(f"\nВсего {result.elapsed:.1f} с.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
