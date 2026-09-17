"""Day 1 acceptance tool.

Proves the audio layer on real hardware rather than in a test double:

    python tools/audio_check.py devices          list what can be captured
    python tools/audio_check.py record            record the default microphone
    python tools/audio_check.py record --system   record what the speakers play
    python tools/audio_check.py routing           check for a feedback loop

Writes a WAV so the result can be listened to, and prints the VAD's view of it,
because "the meter moved" and "the recording contains speech" are different
claims.
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lt_core.audio.capture import CaptureError, open_source  # noqa: E402
from lt_core.audio.devices import (  # noqa: E402
    default_device,
    find_device,
    list_capture_devices,
)
from lt_core.audio.echo_gate import EchoGate, check_routing  # noqa: E402
from lt_core.audio.permissions import check_microphone_permission  # noqa: E402
from lt_core.audio.types import TARGET_SAMPLE_RATE  # noqa: E402
from lt_core.audio.vad import SpeechSegmenter, StreamingVad  # noqa: E402
from lt_core.runtime import bootstrap  # noqa: E402


def cmd_devices(_: argparse.Namespace) -> int:
    devices = list_capture_devices()
    if not devices:
        print("Устройств захвата не найдено.")
        return 1
    print(f"Устройств: {len(devices)}\n")
    for device in devices:
        print(f"  {device.key:22s} {device.label}")
        print(f"  {'':22s} {device.sample_rate} Гц, {device.channels} кан.")
    print("\n★ — устройство по умолчанию;  ⚠ — частота ниже 16 кГц, "
          "распознавание будет заметно хуже.")

    permission = check_microphone_permission()
    if not permission.allowed:
        print(f"\nМИКРОФОНЫ НЕДОСТУПНЫ: {permission.reason}")
        print(f"  {permission.remedy}")
        print("  Захват звука системы этим ограничением не затронут.")
    return 0


def cmd_routing(args: argparse.Namespace) -> int:
    device = find_device(args.device) if args.device else default_device("system")
    if device is None:
        print("Нет устройства для проверки.")
        return 1
    advice = check_routing(device, args.playback)
    print(f"Захват:  {device.label}")
    print(f"Озвучка: {args.playback or '(не выбрана)'}\n")
    print(("БЕЗОПАСНО: " if advice.safe else "ПЕТЛЯ: ") + advice.reason)
    if advice.remedy:
        print(f"Решение:  {advice.remedy}")
    return 0 if advice.safe else 2


def cmd_record(args: argparse.Namespace) -> int:
    kind = "system" if args.system else "microphone"
    device = find_device(args.device) if args.device else default_device(kind)
    if device is None:
        print(f"Не найдено устройство типа «{kind}».")
        return 1

    print(f"Источник: {device.label}")
    if device.is_low_quality:
        print(f"  ВНИМАНИЕ: {device.sample_rate} Гц — для распознавания этого мало.")
    if args.system:
        print("  Включите любой звук, иначе запишется тишина.")
    print(f"Запись {args.seconds:.0f} с...\n")

    gate = EchoGate()
    vad, segmenter = StreamingVad(), SpeechSegmenter()
    collected: list[np.ndarray] = []
    events = []
    started = time.perf_counter()

    source = open_source(device)
    try:
        for chunk in source.stream():
            chunk = gate.filter(chunk)
            collected.append(chunk.samples)
            events += segmenter.push(vad.push(chunk.samples))
            elapsed = time.perf_counter() - started
            bar = "#" * int(min(1.0, float(np.abs(chunk.samples).max()) * 3) * 30)
            print(f"\r  {elapsed:5.1f}s |{bar:<30}| "
                  f"{'речь' if segmenter.in_speech else '    '}", end="")
            if elapsed >= args.seconds:
                break
    except CaptureError as error:
        print(f"\n\n{error}")
        if error.detail:
            print(f"\nПодробности для лога:\n  {error.detail}")
        # Suggesting another device is only helpful if another device could
        # work. Under a permission block, none of them will.
        blocked = kind == "microphone" and not check_microphone_permission().allowed
        alternatives = [] if blocked else [
            d for d in list_capture_devices()
            if d.kind == kind and d.key != device.key
        ][:3]
        if alternatives:
            print("\nПопробуйте другое устройство:")
            for alternative in alternatives:
                print(f"  --device {alternative.key:22s} {alternative.label}")
        return 1
    finally:
        source.stop()
    events += segmenter.flush()
    print()

    audio = np.concatenate(collected) if collected else np.zeros(0, dtype=np.float32)
    if audio.size == 0:
        print("\nНичего не записано — устройство не отдало ни одного блока.")
        return 1

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(TARGET_SAMPLE_RATE)
        wav.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())

    peak = float(np.abs(audio).max())
    rms = float(np.sqrt(np.mean(audio ** 2)))
    starts = [e for e in events if e.kind == "speech_start"]
    ends = [e for e in events if e.kind == "speech_end"]
    speech = sum(e.time for e in ends) - sum(e.time for e in starts)

    print(f"\nЗаписано:   {audio.size / TARGET_SAMPLE_RATE:.2f} с -> {out}")
    print(f"Уровень:    пик {peak:.3f}, RMS {rms:.4f}")
    print(f"Речь:       {len(starts)} сегментов, {speech:.1f} с")
    print(f"Потеряно:   {source.dropped_blocks} блоков")
    if gate.muted_chunks:
        print(f"Затвор:     заглушено {gate.muted_seconds:.1f} с собственной озвучки")
    if peak < 0.001:
        print("\nТИШИНА. Проверьте, что выбран нужный источник и звук действительно идёт.")
        return 1
    return 0


def main() -> int:
    bootstrap()
    parser = argparse.ArgumentParser(description="Проверка аудиослоя")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="перечислить устройства").set_defaults(
        func=cmd_devices)

    record = sub.add_parser("record", help="записать и проанализировать")
    record.add_argument("--system", action="store_true",
                        help="захват звука системы вместо микрофона")
    record.add_argument("--device", help="ключ устройства, например sounddevice:23")
    record.add_argument("--seconds", type=float, default=5.0)
    record.add_argument("--out", default="spike/audio/capture_check.wav")
    record.set_defaults(func=cmd_record)

    routing = sub.add_parser("routing", help="проверить риск акустической петли")
    routing.add_argument("--device", help="ключ устройства захвата")
    routing.add_argument("--playback", help="имя устройства вывода озвучки")
    routing.set_defaults(func=cmd_routing)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
