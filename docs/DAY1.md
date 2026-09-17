# Day 1 — audio layer (2026-09-17)

Target languages narrowed by the client to eight: en, de, ru, zh, ja, es, it, fr.

## Built

`lt_core/runtime.py` — process bootstrap closing the three infrastructure findings
from Day 0 permanently (CUDA DLL directories, huggingface symlinks, UTF-8 output).

`lt_core/audio/` — capture from microphone, WASAPI loopback and media files behind
one interface; everything downstream receives mono float32 at 16 kHz with
session-relative timestamps. Streaming Silero VAD with state carried across calls.
Echo gate plus routing check.

`tools/audio_check.py`, `tools/echo_loop_check.py` — acceptance on real hardware.

37 tests, all passing.

## Acceptance

Criterion was: capture speech from microphone and from the system output, with no
feedback loop.

**System audio: passed, measured.** Playing speech into the default output while
capturing that same output via loopback -- the exact arrangement that causes the
loop. Gate off: 7.4 s reached the pipeline, peak 0.80, one speech segment of 5.2 s.
Gate on: 2.0 s reached the pipeline (the windows outside playback, by design),
peak 0.013, zero speech segments.

**Microphone: implemented and unit-tested, not verifiable on this machine.**
Windows 11 currently denies desktop programs microphone access here, so all ten
microphones enumerate and none open. This is now detected and explained rather
than surfaced as a driver error. To verify after enabling the setting:

    python tools/audio_check.py record --seconds 5

## Findings

1. **A lossy queue silently truncated files.** Decoding outran the VAD by ~50x;
   16.6 s of a 47 s file disappeared with no error raised anywhere -- the
   transcript would simply have come out short. Back-pressure is now chosen per
   source: live capture drops the oldest block (freshest audio wins), offline
   blocks until the consumer catches up.
2. **soxr withholds a filter's worth of audio**, so every stream lost its tail:
   17 ms from 44.1 kHz, 50 ms from 22.05 kHz. At the end of a recording that is a
   truncated final word. All three sources now flush.
3. **An idle WASAPI endpoint returns nothing at all** -- not silence, nothing.
   Measured: five seconds of waiting, zero blocks. Three bugs in one: a consumer
   blocks forever so the UI looks frozen from the moment the user presses start;
   nothing distinguishes "nobody is speaking" from "capture is broken"; and every
   silent gap would be missing from the timeline, drifting subtitles earlier by
   exactly the length of the pauses. The loopback source now keeps its own clock
   and manufactures the silence the device declines to send. Residual drift is
   constant at +0.10 s, not cumulative.
4. **Windows lists one microphone once per host API**, at a different sample rate
   each time -- one webcam mic appeared four times at 44100/44100/48000/32000 Hz
   under identical names. Choosing blind gives the user a 1-in-4 chance of the
   best backing. Now deduplicated, ranked, with the rest kept as fallbacks.
5. **sounddevice and PyAudioWPatch index spaces overlap.** Index 25 was a Realtek
   microphone to one library and a Realtek loopback to the other. Devices are
   keyed by backend and index together.
6. **Enumeration is not a promise.** A disconnected webcam still lists under four
   host APIs, passes `check_input_settings`, and fails to open on all four.
   Opening now walks the fallback chain.
7. **Windows 11 denies desktop microphone access while enumerating every device
   normally.** PortAudio reports it as "Invalid device [PaErrorCode -9996]" --
   nothing mentions permission. The consent key is read directly and reported as
   what it is. Loopback capture is unaffected, which is why this is easy to
   misdiagnose as broken hardware.
8. **Bluetooth headsets expose an 8 kHz Hands-Free microphone** whose name gives
   no hint that it is unusable for recognition. Flagged in the picker.

## Note for Day 5

The Bluetooth headset is this machine's default output. Its latency is why the
echo gate's tail defaults to 300 ms; synthesised speech reaches the ear well
after we hand Windows the buffer, and closing the gate early re-captures our own
last syllable -- one word is enough to start the loop.
