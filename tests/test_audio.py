"""Day 1 audio layer: capture, resampling, VAD, echo gate."""

from __future__ import annotations

import time
import wave

import numpy as np
import pytest

from lt_core.audio.capture import BLOCK_SAMPLES, QUEUE_BLOCKS, CaptureError, FileSource
from lt_core.audio.echo_gate import EchoGate, check_routing
from lt_core.audio.resample import StreamResampler, pcm16_to_float32, to_mono
from lt_core.audio.types import TARGET_SAMPLE_RATE, AudioChunk, DeviceInfo
from lt_core.audio.vad import SpeechSegmenter, StreamingVad


def write_wav(path, samples: np.ndarray, rate: int, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(np.clip(samples * 32767, -32768, 32767).astype(np.int16).tobytes())


def tone(freq: float, seconds: float, rate: int) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# -- types ---------------------------------------------------------------

def test_chunk_rejects_wrong_dtype():
    with pytest.raises(TypeError):
        AudioChunk(samples=np.zeros(10, dtype=np.float64), start_time=0.0)


def test_chunk_rejects_stereo():
    with pytest.raises(ValueError):
        AudioChunk(samples=np.zeros((10, 2), dtype=np.float32), start_time=0.0)


def test_chunk_timing():
    chunk = AudioChunk(np.zeros(8000, dtype=np.float32), start_time=1.5)
    assert chunk.duration == pytest.approx(0.5)
    assert chunk.end_time == pytest.approx(2.0)


def test_low_quality_device_is_flagged():
    """A Bluetooth headset in Hands-Free mode reports 8 kHz and sounds awful.

    The name gives the user no clue, so the flag is the only warning they get.
    """
    hfp = DeviceInfo("sounddevice", 1, "Headset", "microphone", 8_000, 1)
    ok = DeviceInfo("sounddevice", 2, "Headset", "microphone", 48_000, 1)
    assert hfp.is_low_quality and not ok.is_low_quality
    assert "8000" in hfp.label


def test_device_key_is_unique_across_backends():
    """sounddevice and PyAudioWPatch index spaces overlap; keys must not."""
    mic = DeviceInfo("sounddevice", 25, "Realtek", "microphone", 44_100, 2)
    loop = DeviceInfo("wasapi-loopback", 25, "Realtek", "system", 48_000, 2)
    assert mic.key != loop.key


# -- resampling ----------------------------------------------------------

def test_to_mono_averages_channels():
    interleaved = np.array([1.0, 0.0, 1.0, 0.0], dtype=np.float32)
    assert to_mono(interleaved, 2).tolist() == [0.5, 0.5]


def test_to_mono_discards_partial_frame():
    interleaved = np.array([1.0, 0.0, 1.0], dtype=np.float32)
    assert to_mono(interleaved, 2).tolist() == [0.5]


def test_pcm16_round_trip():
    raw = np.array([0, 16384, -16384], dtype=np.int16).tobytes()
    assert pcm16_to_float32(raw) == pytest.approx([0.0, 0.5, -0.5], abs=1e-4)


def resample_tone(freq: float, rate: int) -> np.ndarray:
    resampler = StreamResampler(rate, 1)
    signal = tone(freq, 1.0, rate)
    out = [resampler.process(signal[i:i + 1024]) for i in range(0, signal.size, 1024)]
    out.append(resampler.flush())
    return np.concatenate(out)


def test_resampler_preserves_duration():
    """The tail inside the filter must come out, or every file loses its end."""
    out = resample_tone(440, 44_100)
    assert out.size == pytest.approx(TARGET_SAMPLE_RATE, rel=0.001)


def test_resampler_is_band_limited():
    """A tone above the 8 kHz Nyquist limit must be removed, not folded back.

    Index-picking (the Day 0 shortcut) aliases a 12 kHz tone down to 4 kHz,
    landing it squarely in the speech band as a loud phantom. Measured against
    an in-band tone, because the absolute level of a correctly-filtered signal
    is just numerical noise and proves nothing on its own.
    """
    in_band = np.sqrt(np.mean(resample_tone(1_000, 44_100) ** 2))
    out_of_band = np.sqrt(np.mean(resample_tone(12_000, 44_100) ** 2))
    assert out_of_band < in_band / 100


def test_resampler_passthrough_at_target_rate():
    signal = tone(440, 0.1, TARGET_SAMPLE_RATE)
    out = StreamResampler(TARGET_SAMPLE_RATE, 1).process(signal)
    assert np.array_equal(out, signal)


# -- capture -------------------------------------------------------------

def test_file_source_reads_every_sample(tmp_path):
    path = tmp_path / "speech.wav"
    write_wav(path, tone(440, 3.0, 22_050), 22_050)
    chunks = list(FileSource(path).stream())
    total = sum(c.samples.size for c in chunks)
    assert total / TARGET_SAMPLE_RATE == pytest.approx(3.0, abs=0.02)


def test_file_source_timestamps_are_contiguous(tmp_path):
    path = tmp_path / "speech.wav"
    write_wav(path, tone(440, 1.0, 16_000), 16_000)
    chunks = list(FileSource(path).stream())
    for earlier, later in zip(chunks, chunks[1:]):
        assert later.start_time == pytest.approx(earlier.end_time, abs=1e-9)


def test_offline_source_never_drops_audio_when_consumer_is_slow(tmp_path):
    """Regression: a slow consumer silently truncated files.

    Decoding outruns downstream processing by a wide margin -- roughly 50x for
    VAD alone. With a lossy queue, a 47 s file arrived as 30.6 s with no error
    raised anywhere; the transcript was simply short. An offline source must
    apply back-pressure instead.
    """
    path = tmp_path / "long.wav"
    seconds = 12.0
    write_wav(path, tone(440, seconds, 16_000), 16_000)

    source = FileSource(path)
    expected_blocks = int(seconds * TARGET_SAMPLE_RATE / BLOCK_SAMPLES)
    assert expected_blocks > QUEUE_BLOCKS, "test must overflow the queue to be meaningful"

    total = 0
    for index, chunk in enumerate(source.stream()):
        if index % 60 == 0:
            time.sleep(0.005)  # stand in for a GPU stall
        total += chunk.samples.size

    assert source.dropped_blocks == 0
    assert total / TARGET_SAMPLE_RATE == pytest.approx(seconds, abs=0.02)


def test_realtime_file_source_is_lossy(tmp_path):
    """The live simulation must behave like live capture, drops included."""
    path = tmp_path / "live.wav"
    write_wav(path, tone(440, 0.5, 16_000), 16_000)
    assert FileSource(path, realtime=True).lossy is True
    assert FileSource(path, realtime=False).lossy is False


def test_missing_file_raises_capture_error(tmp_path):
    with pytest.raises(CaptureError, match="no such file"):
        list(FileSource(tmp_path / "absent.wav").stream())


def test_unreadable_media_raises_capture_error(tmp_path):
    path = tmp_path / "broken.mp3"
    path.write_bytes(b"this is not audio")
    with pytest.raises(CaptureError):
        list(FileSource(path).stream())


# -- VAD -----------------------------------------------------------------

@pytest.fixture(scope="module")
def vad():
    return StreamingVad()


def test_vad_is_quiet_on_silence(vad):
    vad.reset()
    quiet = (np.random.default_rng(0).standard_normal(16_000) * 0.0005).astype(np.float32)
    assert max(vad.push(quiet)) < 0.3


def test_vad_buffers_partial_frames(vad):
    vad.reset()
    assert vad.push(np.zeros(100, dtype=np.float32)) == []
    assert len(vad.push(np.zeros(500, dtype=np.float32))) == 1


def test_vad_frame_count_is_independent_of_chunking(vad):
    """State carries across calls, so chunk size must not change the result."""
    signal = tone(300, 2.0, TARGET_SAMPLE_RATE)
    vad.reset()
    whole = vad.push(signal)
    vad.reset()
    piecemeal: list[float] = []
    for i in range(0, signal.size, 137):  # deliberately not a frame multiple
        piecemeal += vad.push(signal[i:i + 137])
    assert len(whole) == len(piecemeal)
    assert np.allclose(whole, piecemeal, atol=1e-5)


def test_segmenter_ignores_a_cough():
    """A burst shorter than min_speech must never be announced at all."""
    segmenter = SpeechSegmenter(min_speech=0.20, min_silence=0.10)
    events = segmenter.push([0.9] * 2 + [0.0] * 20)
    assert events == []


def test_segmenter_reports_a_real_utterance():
    segmenter = SpeechSegmenter(min_speech=0.05, min_silence=0.10, speech_pad=0.0)
    events = segmenter.push([0.9] * 40 + [0.0] * 20)
    assert [e.kind for e in events] == ["speech_start", "speech_end"]
    assert events[0].time < events[1].time


def test_segmenter_bridges_a_pause_between_words():
    """A gap shorter than min_silence stays inside one segment."""
    segmenter = SpeechSegmenter(min_speech=0.05, min_silence=0.50, speech_pad=0.0)
    events = segmenter.push([0.9] * 20 + [0.0] * 5 + [0.9] * 20)
    assert [e.kind for e in events] == ["speech_start"]


def test_segmenter_flush_closes_an_open_segment():
    segmenter = SpeechSegmenter(min_speech=0.05, min_silence=0.50)
    segmenter.push([0.9] * 40)
    assert [e.kind for e in segmenter.flush()] == ["speech_end"]
    assert segmenter.flush() == []


# -- echo gate -----------------------------------------------------------

def loopback(name: str) -> DeviceInfo:
    return DeviceInfo("wasapi-loopback", 1, name, "system", 48_000, 2,
                      mirrors_output=name)


def test_routing_rejects_capturing_the_device_we_speak_into():
    advice = check_routing(loopback("Kopfhörer"), "Kopfhörer")
    assert not advice.safe
    assert advice.remedy


def test_routing_accepts_separate_devices():
    assert check_routing(loopback("Lautsprecher"), "Kopfhörer").safe


def test_routing_accepts_a_microphone():
    mic = DeviceInfo("sounddevice", 3, "Webcam", "microphone", 48_000, 1)
    assert check_routing(mic, "Webcam").safe


def test_gate_mutes_while_speaking():
    gate = EchoGate(tail=0.0)
    chunk = AudioChunk(np.ones(512, dtype=np.float32), start_time=1.0)
    assert not gate.filter(chunk).muted

    with gate.playing():
        muted = gate.filter(chunk)
    assert muted.muted
    assert not muted.samples.any()
    assert muted.start_time == chunk.start_time, "timeline must not shift"


def test_gate_holds_shut_for_the_device_latency_tail():
    """Reopening the instant playback ends re-captures our own last syllable.

    Bluetooth output lags 150-250 ms behind the buffer we hand Windows, and one
    captured word is enough to start the loop.
    """
    gate = EchoGate(tail=0.25)
    with gate.playing():
        pass
    assert gate.is_shut
    time.sleep(0.30)
    assert not gate.is_shut


def test_gate_counts_what_it_suppressed():
    gate = EchoGate(tail=0.0)
    chunk = AudioChunk(np.ones(1600, dtype=np.float32), start_time=0.0)
    with gate.playing():
        for _ in range(3):
            gate.filter(chunk)
    assert gate.muted_chunks == 3
    assert gate.muted_seconds == pytest.approx(0.3)


def test_gate_extend_covers_queued_audio():
    gate = EchoGate(tail=0.05)
    gate.extend(0.5)
    assert gate.is_shut


# -- permissions ---------------------------------------------------------

def test_permission_reports_denied_desktop_access(monkeypatch):
    """An explicit Deny on the desktop-apps toggle is a real denial."""
    import lt_core.audio.permissions as permissions

    monkeypatch.setattr(permissions.sys, "platform", "win32")
    monkeypatch.setattr(
        permissions, "_read_value",
        lambda root, subkey: "Deny" if subkey.endswith("NonPackaged") else "Allow",
    )
    result = permissions.check_microphone_permission()
    assert not result.allowed
    assert result.remedy and "классическим" in result.remedy.lower()


def test_absent_consent_value_is_not_a_denial(monkeypatch):
    """Regression: inferring denial from a missing value gave a wrong verdict.

    The value was absent, ten microphones were failing, and the conclusion --
    permission is off -- was confident and false. The toggle was on; PortAudio
    was the thing broken. A never-written setting is not a denied one.
    """
    import lt_core.audio.permissions as permissions

    monkeypatch.setattr(permissions.sys, "platform", "win32")
    monkeypatch.setattr(
        permissions, "_read_value",
        lambda root, subkey: None if subkey.endswith("NonPackaged") else "Allow",
    )
    assert permissions.check_microphone_permission().allowed


def test_permission_reports_global_denial(monkeypatch):
    import lt_core.audio.permissions as permissions

    monkeypatch.setattr(permissions.sys, "platform", "win32")
    monkeypatch.setattr(permissions, "_read_value", lambda root, subkey: "Deny")
    assert not permissions.check_microphone_permission().allowed


def test_permission_allows_when_both_toggles_are_on(monkeypatch):
    import lt_core.audio.permissions as permissions

    monkeypatch.setattr(permissions.sys, "platform", "win32")
    monkeypatch.setattr(permissions, "_read_value", lambda root, subkey: "Allow")
    assert permissions.check_microphone_permission().allowed


def test_open_failure_blames_permission_before_hardware(monkeypatch):
    """A denied microphone must not be reported as unplugged hardware."""
    import lt_core.audio.permissions as permissions

    monkeypatch.setattr(permissions.sys, "platform", "win32")
    monkeypatch.setattr(permissions, "_read_value", lambda root, subkey: "Deny")
    message = permissions.explain_open_failure("Webcam")
    assert "конфиденциальност" in message.lower()
    assert "Webcam" not in message


def test_open_failure_points_at_the_other_backend(monkeypatch):
    """With permission fine, the useful advice is to try DirectShow."""
    import lt_core.audio.permissions as permissions

    monkeypatch.setattr(permissions.sys, "platform", "win32")
    monkeypatch.setattr(permissions, "_read_value", lambda root, subkey: "Allow")
    assert "DirectShow" in permissions.explain_open_failure("Webcam")


def test_open_failure_falls_back_to_hardware_explanation(monkeypatch):
    import lt_core.audio.permissions as permissions

    monkeypatch.setattr(permissions.sys, "platform", "win32")
    monkeypatch.setattr(permissions, "_read_value", lambda root, subkey: "Allow")
    assert "Webcam" in permissions.explain_open_failure("Webcam")


def test_device_exposes_every_way_to_open_it():
    """One name, several host-API backings; a dead one must not be the end."""
    device = DeviceInfo("sounddevice", 23, "Webcam", "microphone", 48_000, 2,
                        alternates=((10, 44_100, 2), (1, 44_100, 2)))
    assert device.openings == ((23, 48_000, 2), (10, 44_100, 2), (1, 44_100, 2))
