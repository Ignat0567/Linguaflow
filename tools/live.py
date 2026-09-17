"""Live translation from the command line.

    python tools/live.py                       microphone, transcribe only
    python tools/live.py --to ru               microphone, translated
    python tools/live.py --system --to en      what the speakers are playing
    python tools/live.py --replay talk.wav     a recording, paced as if live

`--replay` is how the streaming path gets tested without a person talking into
a microphone for fifteen minutes: the file is fed at wall-clock speed, drops
included, so the session cannot tell the difference.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lt_core.asr.transcriber import SUPPORTED_LANGUAGES, Transcriber  # noqa: E402
from lt_core.audio.capture import CaptureError, FileSource, open_source  # noqa: E402
from lt_core.audio.devices import default_device, find_device  # noqa: E402
from lt_core.mt.translator import build_translator  # noqa: E402
from lt_core.mt.types import TranslationError, TranslationMode  # noqa: E402
from lt_core.realtime.conversation import ConversationSession, Side  # noqa: E402
from lt_core.realtime.session import PACES, LiveSession  # noqa: E402

MODEL_ROOT = Path(__file__).resolve().parent.parent / "models"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="linguaflow-live",
        description="Linguaflow — перевод речи в реальном времени")
    parser.add_argument("--device", help="ключ устройства захвата")
    parser.add_argument("--system", action="store_true",
                        help="захват звука системы вместо микрофона")
    parser.add_argument("--replay", help="файл вместо живого звука, в темпе записи")
    parser.add_argument("--language", "-l", choices=sorted(SUPPORTED_LANGUAGES),
                        help="язык речи; по умолчанию определяется сам")
    parser.add_argument("--to", "-t", choices=sorted(SUPPORTED_LANGUAGES),
                        help="язык перевода")
    parser.add_argument("--pace", choices=sorted(PACES), default="balanced",
                        help="fast — быстрее и подвижнее; steady — позже и устойчивее")
    parser.add_argument("--mode", choices=[TranslationMode.OFFLINE,
                                           TranslationMode.ONLINE],
                        default=TranslationMode.OFFLINE)
    parser.add_argument("--service", default="deepl")
    parser.add_argument("--api-key")
    parser.add_argument("--conversation", metavar="LANG",
                        help="режим «Разговор»: язык второго собеседника "
                             "(первый задаётся через --language)")
    parser.add_argument("--seconds", type=float,
                        help="остановиться через столько секунд")
    args = parser.parse_args()

    pace = PACES[args.pace]

    translator = None
    if args.to:
        options = {"api_key": args.api_key} if args.api_key else {}
        if args.mode == TranslationMode.ONLINE:
            options["service"] = args.service
        try:
            translator = build_translator(args.mode, model_root=MODEL_ROOT, **options)
        except TranslationError as error:
            print(str(error))
            return 1

    print("Загружаю модели...", end="", flush=True)
    started = time.perf_counter()
    transcriber = Transcriber(model_root=MODEL_ROOT)
    print(f"\rМодели: {transcriber.device} ({transcriber.compute_type}), "
          f"{time.perf_counter() - started:.1f} с")

    if args.replay:
        source = FileSource(args.replay, realtime=True)
        origin = Path(args.replay).name
    else:
        kind = "system" if args.system else "microphone"
        device = find_device(args.device) if args.device else default_device(kind)
        if device is None:
            print(f"Не найдено устройство типа «{kind}».")
            return 1
        source = open_source(device)
        origin = device.label

    if args.conversation:
        if not args.language:
            print("Для режима «Разговор» укажите язык первого собеседника: --language")
            return 2
        if translator is None:
            print("Для режима «Разговор» нужен перевод: добавьте --to "
                  "(язык роли не играет, направления берутся из пары).")
            return 2
        session = ConversationSession(
            transcriber, translator,
            Side(args.language, f"A · {SUPPORTED_LANGUAGES[args.language]}"),
            Side(args.conversation, f"B · {SUPPORTED_LANGUAGES[args.conversation]}"),
            pace=pace,
        )
    else:
        session = LiveSession(
            transcriber,
            translator=translator,
            source_language=args.language,
            target_language=args.to,
            pace=pace,
        )

    print(f"Источник:  {origin}")
    print(f"Темп:      {args.pace} — окно {pace.window:.0f} с, "
          f"ожидаемая задержка ~{pace.expected_delay:.1f} с")
    if translator is not None:
        print(f"Перевод:   {translator.provider.name} → "
              f"{SUPPORTED_LANGUAGES.get(args.to, args.to)}")
    print("Ctrl+C — остановить.\n")

    begin = time.perf_counter()
    try:
        for chunk in source.stream():
            produced = session.feed(chunk)
            for update in (produced if isinstance(produced, list) else [produced]):
                if update is not None and update.has_content:
                    _show(update)
            if args.seconds and time.perf_counter() - begin > args.seconds:
                break
    except CaptureError as error:
        print(f"\n{error}")
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        source.stop()

    if isinstance(session, ConversationSession):
        stats = session.stats
    else:
        final = session.finish()
        if final.has_content:
            _show(final)
        stats = session.stats
    print("\n" + "-" * 60)
    print(f"Звука:        {stats.audio_seconds:.0f} с за "
          f"{time.perf_counter() - begin:.0f} с")
    print(f"Проходов:     {stats.ticks}  "
          f"(ASR {stats.asr_seconds:.1f} с, перевод {stats.mt_seconds:.1f} с)")
    print(f"Загрузка:     {stats.realtime_factor:.2f} от реального времени "
          f"({'запас есть' if stats.realtime_factor < 0.8 else 'на пределе'})")
    print(f"Задержка:     медиана {stats.median_lag:.1f} с, "
          f"максимум {stats.worst_lag:.1f} с")
    print(f"Буфер:        максимум {stats.max_buffer_seconds:.1f} с "
          f"(принудительных фиксаций {stats.forced_commits}, "
          f"обрезок {stats.forced_trims})")
    print(f"Текст:        {stats.committed_words} слов зафиксировано")
    return 0


def _show(update) -> None:
    who = f"[{update.speaker}] " if update.speaker else ""
    if update.committed:
        print(f"  {who}{update.committed}")
    if update.translation:
        print(f"    → {update.translation}")
    if update.partial:
        print(f"    … {update.partial}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
