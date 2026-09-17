"""Audio capture.

Three sources, one interface. Whatever the origin, a source yields AudioChunks
of mono float32 at 16 kHz with session-relative timestamps, so the ASR stage
never learns where its audio came from.

Capture runs on a background thread owned by the source and hands blocks over a
bounded queue. Bounded matters: if a consumer stalls (a GPU hiccup, a slow
repaint), an unbounded queue would grow until the process dies, minutes after
the actual fault. Here the oldest audio is dropped and the loss is counted, so
the stall is visible while it is happening.
"""

from __future__ import annotations

import queue
import threading
import wave
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from .resample import StreamResampler, pcm16_to_float32
from .types import TARGET_SAMPLE_RATE, AudioChunk, DeviceInfo

# 32 ms at 16 kHz: one Silero VAD frame, so the VAD never has to re-buffer.
BLOCK_SAMPLES = 512
# ~8 s of audio. Long enough to ride out a GPU stall, short enough that a real
# deadlock surfaces as dropped audio rather than swallowed memory.
QUEUE_BLOCKS = 250


class CaptureError(RuntimeError):
    """A capture failure with a message fit to show a user.

    `detail` carries the driver's own words -- PortAudio error codes, host API
    complaints -- which belong in a log, not in front of someone who wants to
    translate a meeting.
    """

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class AudioSource(ABC):
    """A running capture session.

    `lossy` decides what happens when the consumer falls behind, and the two
    answers are opposites:

    A live source cannot pause the world. A microphone keeps producing whether
    or not the GPU is ready, so the only choices are to drop audio or to drift
    ever further behind real time. Dropping the oldest block is right: in a
    live translation the freshest audio is the useful one.

    A file has no such constraint, and dropping from one is data loss. It is
    also invisible data loss -- the transcript simply comes out short, with no
    error anywhere. This bit the Day 1 acceptance run: decoding ran ~50x faster
    than the VAD consuming it, and 16.6 seconds of a 47-second file evaporated
    before anyone noticed. An offline source therefore blocks instead.
    """

    lossy: bool = True

    def __init__(self) -> None:
        self._queue: queue.Queue[AudioChunk | None] = queue.Queue(maxsize=QUEUE_BLOCKS)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._samples_emitted = 0
        self._dropped_blocks = 0
        self._error: BaseException | None = None

    # -- lifecycle -------------------------------------------------------
    @abstractmethod
    def _run(self) -> None:
        """Read from the device until _stop is set, calling _emit()."""

    def start(self) -> None:
        if self._thread is not None:
            raise CaptureError("source already started")
        self._thread = threading.Thread(
            target=self._pump, name=type(self).__name__, daemon=True
        )
        self._thread.start()

    def _pump(self) -> None:
        try:
            self._run()
        except BaseException as exc:  # surfaced to the consumer in stream()
            self._error = exc
        finally:
            self._queue.put(None)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> "AudioSource":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # -- data ------------------------------------------------------------
    def _emit(self, mono16k: np.ndarray) -> None:
        if mono16k.size == 0:
            return
        chunk = AudioChunk(
            samples=mono16k.astype(np.float32, copy=False),
            start_time=self._samples_emitted / TARGET_SAMPLE_RATE,
        )
        self._samples_emitted += mono16k.size

        if not self.lossy:
            # Offline: wait for the consumer. Poll rather than block forever so
            # stop() is still honoured if the consumer has gone away entirely.
            while not self._stop.is_set():
                try:
                    self._queue.put(chunk, timeout=0.1)
                    return
                except queue.Full:
                    continue
            return

        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._dropped_blocks += 1
                self._queue.put_nowait(chunk)
            except (queue.Empty, queue.Full):
                self._dropped_blocks += 1

    def stream(self) -> Iterator[AudioChunk]:
        """Yield chunks until the source ends. Re-raises capture failures."""
        if self._thread is None:
            self.start()
        while True:
            item = self._queue.get()
            if item is None:
                break
            yield item
        if self._error is not None:
            if isinstance(self._error, CaptureError):
                raise self._error
            raise CaptureError(str(self._error)) from self._error

    @property
    def dropped_blocks(self) -> int:
        return self._dropped_blocks


class MicrophoneSource(AudioSource):
    """Capture from an input device via sounddevice."""

    def __init__(self, device: DeviceInfo) -> None:
        super().__init__()
        if device.backend != "sounddevice":
            raise CaptureError(f"{device.name} is not a sounddevice input")
        self.device = device

    def _run(self) -> None:
        """Open the device, trying each host-API backing in turn.

        Enumeration is not a promise. Windows keeps entries for hardware that
        has been unplugged, and a device that lists cleanly -- correct name,
        plausible sample rate, `check_input_settings` satisfied -- can still
        refuse to open. The Day 1 machine listed a webcam microphone under four
        host APIs while the webcam was disconnected; all four failed.

        So a failure to open one backing is not a failure of the device, and
        whatever PortAudio says about it ("Invalid device [PaErrorCode -9996]")
        is not something to show a user.
        """
        import sounddevice as sd

        attempts: list[str] = []
        for index, rate, max_channels in self.device.openings:
            channels = min(max_channels, 2)
            try:
                stream = sd.InputStream(
                    device=index,
                    samplerate=rate,
                    channels=channels,
                    dtype="float32",
                    blocksize=max(1, round(BLOCK_SAMPLES * rate / TARGET_SAMPLE_RATE)),
                )
                stream.start()
            except Exception as exc:
                attempts.append(f"#{index} @ {rate} Hz: {exc}")
                continue
            self._read_until_stopped(stream, rate, channels)
            return

        from .permissions import explain_open_failure

        raise CaptureError(
            explain_open_failure(self.device.name),
            detail="; ".join(attempts),
        )

    def _read_until_stopped(self, stream, rate: int, channels: int) -> None:
        resampler = StreamResampler(rate, channels)
        blocksize = max(1, round(BLOCK_SAMPLES * rate / TARGET_SAMPLE_RATE))
        try:
            while not self._stop.is_set():
                frames, overflowed = stream.read(blocksize)
                if overflowed:
                    self._dropped_blocks += 1
                self._emit(resampler.process(frames.reshape(-1)))
            self._emit(resampler.flush())
        finally:
            stream.stop()
            stream.close()


class SystemAudioSource(AudioSource):
    """Capture what is playing, via WASAPI loopback.

    An idle endpoint produces nothing at all. Windows only runs the render
    engine for a device while some application holds an active stream on it, so
    with nothing playing, loopback capture does not return silence -- it
    returns no data whatsoever, indefinitely. Measured on the Day 1 machine:
    five seconds of waiting, zero blocks.

    Left alone that is three bugs at once. A consumer blocked on the next chunk
    waits forever, so the UI looks frozen from the moment the user presses
    start. Nothing distinguishes "nobody is speaking" from "capture is broken".
    And because the timeline advances by samples emitted, every silent gap
    would be missing from it, so subtitles would drift earlier and earlier
    against the wall clock -- by exactly the length of the pauses.

    So this source keeps its own clock and manufactures the silence the device
    declines to send. Audio time then tracks elapsed time whether or not
    anything is playing.
    """

    # Inject silence once we are this far behind real time. One block would
    # fight normal jitter; three is well clear of it and still only ~100 ms.
    _SILENCE_THRESHOLD_BLOCKS = 3

    def __init__(self, device: DeviceInfo) -> None:
        super().__init__()
        if device.backend != "wasapi-loopback":
            raise CaptureError(f"{device.name} is not a loopback device")
        self.device = device
        self._silence_blocks = 0

    @property
    def silence_blocks(self) -> int:
        """Blocks manufactured because the device sent nothing."""
        return self._silence_blocks

    def _run(self) -> None:
        import time

        import pyaudiowpatch as pyaudio

        rate = self.device.sample_rate
        channels = self.device.channels
        resampler = StreamResampler(rate, channels)
        blocksize = max(1, round(BLOCK_SAMPLES * rate / TARGET_SAMPLE_RATE))
        block_seconds = BLOCK_SAMPLES / TARGET_SAMPLE_RATE
        silence = np.zeros(BLOCK_SAMPLES, dtype=np.float32)

        pa = pyaudio.PyAudio()
        stream = None
        try:
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=self.device.index,
                frames_per_buffer=blocksize,
            )
            started = time.monotonic()
            while not self._stop.is_set():
                if stream.get_read_available() >= blocksize:
                    raw = stream.read(blocksize, exception_on_overflow=False)
                    self._emit(resampler.process(pcm16_to_float32(raw)))
                    continue

                behind = (time.monotonic() - started) - (
                    self._samples_emitted / TARGET_SAMPLE_RATE
                )
                if behind >= self._SILENCE_THRESHOLD_BLOCKS * block_seconds:
                    self._emit(silence)
                    self._silence_blocks += 1
                else:
                    time.sleep(block_seconds / 4)
            self._emit(resampler.flush())
        finally:
            if stream is not None:
                stream.stop_stream()
                stream.close()
            pa.terminate()


class FileSource(AudioSource):
    """Decode a media file. Any format ffmpeg understands.

    Used both for batch jobs and for replaying a recording through the live
    pipeline, which is how the streaming path gets tested without a human
    talking into a microphone.
    """

    def __init__(self, path: Path | str, realtime: bool = False) -> None:
        super().__init__()
        self.path = Path(path)
        # When True, pace output at wall-clock speed to imitate a live source
        # -- and then behave like one, dropping audio under back-pressure so
        # the simulation stays honest.
        self.realtime = realtime
        self.lossy = realtime

    def _run(self) -> None:
        if not self.path.exists():
            raise CaptureError(f"no such file: {self.path}")
        if self.path.suffix.lower() == ".wav":
            self._run_wav()
        else:
            self._run_ffmpeg()

    def _pace(self, started: float) -> None:
        if not self.realtime:
            return
        import time

        target = self._samples_emitted / TARGET_SAMPLE_RATE
        drift = target - (time.perf_counter() - started)
        if drift > 0:
            time.sleep(drift)

    def _run_wav(self) -> None:
        import time

        started = time.perf_counter()
        with wave.open(str(self.path)) as wav:
            if wav.getsampwidth() != 2:
                # 8-bit, 24-bit and float WAVs exist; let ffmpeg deal with them.
                self._run_ffmpeg()
                return
            resampler = StreamResampler(wav.getframerate(), wav.getnchannels())
            blocksize = max(
                1, round(BLOCK_SAMPLES * wav.getframerate() / TARGET_SAMPLE_RATE)
            )
            while not self._stop.is_set():
                raw = wav.readframes(blocksize)
                if not raw:
                    break
                self._emit(resampler.process(pcm16_to_float32(raw)))
                self._pace(started)
            self._emit(resampler.flush())

    def _run_ffmpeg(self) -> None:
        import subprocess
        import time

        import imageio_ffmpeg

        # Store-Python virtualises paths given to subprocesses; resolve first.
        exe = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve())
        cmd = [
            exe, "-nostdin", "-loglevel", "error",
            "-i", str(self.path.resolve()),
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", "1", "-ar", str(TARGET_SAMPLE_RATE), "-",
        ]
        started = time.perf_counter()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            nbytes = BLOCK_SAMPLES * 2
            while not self._stop.is_set():
                raw = proc.stdout.read(nbytes)
                if not raw:
                    break
                self._emit(pcm16_to_float32(raw))
                self._pace(started)
        finally:
            if proc.poll() is None:
                proc.kill()
            stderr = proc.stderr.read().decode("utf-8", "replace").strip()
            proc.stdout.close()
            proc.stderr.close()
            code = proc.wait()
            if code not in (0, None) and self._samples_emitted == 0:
                raise CaptureError(f"ffmpeg could not decode {self.path.name}: {stderr}")


def open_source(device: DeviceInfo) -> AudioSource:
    if device.kind == "system":
        return SystemAudioSource(device)
    return MicrophoneSource(device)
