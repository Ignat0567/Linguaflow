"""Day 1 acceptance: demonstrate the feedback loop, then close it.

Plays a speech clip into the default output while capturing that same output
via WASAPI loopback -- exactly the arrangement that makes the pipeline
translate its own voice. Runs it twice:

    gate off   the played speech is captured; a loop would form here
    gate on    the same playback is suppressed; nothing to feed back

"Nothing came through" only means something if the same setup demonstrably
does capture audio when the gate is open, so both halves are measured and
compared rather than asserted.

This check makes noise on the default output device, out loud, for about ten
seconds. That is not a detail. Run blind while a call is in progress, the clip
goes into the call and everyone on it hears it -- which is exactly what
happened the first time this ran. Playback is therefore refused unless it is
asked for explicitly.

    python tools/echo_loop_check.py --play-out-loud
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lt_core.audio.capture import SystemAudioSource  # noqa: E402
from lt_core.audio.devices import default_device  # noqa: E402
from lt_core.audio.echo_gate import EchoGate  # noqa: E402
from lt_core.audio.types import TARGET_SAMPLE_RATE  # noqa: E402
from lt_core.audio.vad import SpeechSegmenter, StreamingVad  # noqa: E402
from lt_core.runtime import bootstrap  # noqa: E402

CLIP = Path("spike/audio/ru.wav")
SECONDS = 7.0
PLAY_SECONDS = 5.0


def play(path: Path, done: threading.Event, gate: EchoGate | None) -> None:
    import sounddevice as sd

    with wave.open(str(path)) as wav:
        rate = wav.getframerate()
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        audio = (pcm.astype(np.float32) / 32768.0).reshape(-1, wav.getnchannels())

    # Play no more than we intend to capture. Otherwise playback outlives the
    # measurement and bleeds into the next one -- which is how the first run of
    # this check reported a leak that was entirely its own doing.
    audio = audio[: int(PLAY_SECONDS * rate)]

    if gate is None:
        sd.play(audio, rate)
        sd.wait()
    else:
        # The gate must cover the audio still sitting in the device buffer,
        # not just the time we spend calling play().
        with gate.playing():
            sd.play(audio, rate)
            gate.extend(len(audio) / rate)
            sd.wait()
    done.set()


def capture(label: str, gate: EchoGate | None) -> dict[str, float]:
    device = default_device("system")
    if device is None:
        raise SystemExit("Нет loopback-устройства: WASAPI недоступен.")

    vad, segmenter = StreamingVad(), SpeechSegmenter()
    collected: list[np.ndarray] = []
    # Muted chunks are zeroed, so averaging over the whole capture says more
    # about how long the gate happened to be open than about how well it
    # works. What reached the pipeline is what passed through un-muted.
    passed_through: list[np.ndarray] = []
    events = []
    done = threading.Event()

    source = SystemAudioSource(device)
    source.start()
    time.sleep(0.4)  # let the loopback stream settle before playback starts

    player = threading.Thread(target=play, args=(CLIP, done, gate), daemon=True)
    player.start()

    started = time.perf_counter()
    for chunk in source.stream():
        if gate is not None:
            chunk = gate.filter(chunk)
        collected.append(chunk.samples)
        if not chunk.muted:
            passed_through.append(chunk.samples)
        events += segmenter.push(vad.push(chunk.samples))
        if time.perf_counter() - started > SECONDS:
            break
    source.stop()
    events += segmenter.flush()

    import sounddevice as sd

    sd.stop()  # nothing of this run may still be sounding when the next starts
    player.join(timeout=2.0)

    audio = np.concatenate(collected) if collected else np.zeros(1, dtype=np.float32)
    leaked = (
        np.concatenate(passed_through) if passed_through
        else np.zeros(1, dtype=np.float32)
    )
    starts = [e for e in events if e.kind == "speech_start"]
    ends = [e for e in events if e.kind == "speech_end"]

    result = {
        "seconds": audio.size / TARGET_SAMPLE_RATE,
        "leaked_seconds": leaked.size / TARGET_SAMPLE_RATE,
        "peak": float(np.abs(leaked).max()),
        "rms": float(np.sqrt(np.mean(leaked ** 2))),
        "segments": float(len(starts)),
        "speech": sum(e.time for e in ends) - sum(e.time for e in starts),
    }
    print(f"  {label:12s} до конвейера дошло {result['leaked_seconds']:.1f} с: "
          f"пик {result['peak']:.4f}, RMS {result['rms']:.5f}")
    print(f"  {'':12s} распознано речи: {int(result['segments'])} сегментов, "
          f"{result['speech']:.1f} с")
    return result


def main() -> int:
    bootstrap()
    parser = argparse.ArgumentParser(
        description="Проверка защиты от акустической петли")
    parser.add_argument(
        "--play-out-loud", action="store_true",
        help="разрешить воспроизведение вслух — обязательный флаг")
    args = parser.parse_args()

    if not CLIP.exists():
        print(f"Нет тестового клипа: {CLIP}")
        return 1

    device = default_device("system")
    if device is None:
        print("Нет loopback-устройства: WASAPI недоступен.")
        return 1

    if not args.play_out_loud:
        print("Эта проверка ВОСПРОИЗВОДИТ РЕЧЬ ВСЛУХ около 10 секунд")
        print(f"в устройство «{device.name}» — иначе захватывать нечего.")
        print()
        print("Если идёт звонок или запись, собеседники это услышат.")
        print("Убедившись, что это безопасно, запустите:")
        print()
        print("    python tools/echo_loop_check.py --play-out-loud")
        return 1

    print(f"Захват и воспроизведение на одном устройстве: {device.name}")
    print("Это та самая конфигурация, которая порождает петлю.\n")

    print("1. Затвор выключен — проверяем, что петля вообще возможна:")
    open_gate = capture("без затвора", None)

    time.sleep(2.5)  # let the device go fully quiet between runs

    print("\n2. Затвор включён — та же конфигурация:")
    gate = EchoGate()
    shut = capture("с затвором", gate)
    print(f"  {'':12s} заглушено {gate.muted_seconds:.1f} с "
          f"({gate.muted_chunks} блоков)")

    print("\nИтог:")
    if open_gate["segments"] == 0:
        print("  НЕУБЕДИТЕЛЬНО: без затвора речь тоже не поймана.")
        print("  Проверьте, что воспроизведение идёт в устройство по умолчанию.")
        return 1

    print(f"  Без затвора: {int(open_gate['segments'])} сегментов речи за "
          f"{open_gate['leaked_seconds']:.1f} с -> петля бы замкнулась.")
    print(f"  С затвором:  {int(shut['segments'])} сегментов; "
          f"конвейера достигли только {shut['leaked_seconds']:.1f} с вне окна "
          f"озвучки.")

    if shut["segments"] == 0:
        print("\n  ПРОЙДЕНО: собственная озвучка не возвращается в конвейер.")
        return 0
    print("\n  НЕ ПРОЙДЕНО: речь прошла сквозь затвор.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
