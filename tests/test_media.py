"""Day 2: source resolution and the batch pipeline's contracts."""

from __future__ import annotations

import wave

import numpy as np
import pytest

from lt_core.media import MediaError, is_url, probe


def write_wav(path, seconds: float, rate: int = 16_000) -> None:
    t = np.arange(int(seconds * rate)) / rate
    samples = (0.4 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())


# -- URL detection -------------------------------------------------------

@pytest.mark.parametrize("target", [
    "https://youtube.com/watch?v=x",
    "http://example.com/a.mp3",
    "HTTPS://EXAMPLE.COM/A.MP4",
    "  https://example.com/a.mp4  ",
])
def test_urls_are_recognised(target):
    assert is_url(target)


@pytest.mark.parametrize("target", [
    "C:/video.mp4",
    "/home/user/audio.wav",
    "video.mp4",
    r"E:\Media\talk.m4a",
    "ftp://example.com/a.mp3",
])
def test_paths_are_not_urls(target):
    """A Windows path starts with a drive letter and a colon, which is close
    enough to a scheme to matter. Only http(s) counts."""
    assert not is_url(target)


# -- probing -------------------------------------------------------------

def test_probe_reads_duration(tmp_path):
    path = tmp_path / "clip.wav"
    write_wav(path, 2.5)
    info = probe(path)
    assert info.duration == pytest.approx(2.5, abs=0.05)
    assert info.has_audio
    assert info.title == "clip"


def test_probe_rejects_a_missing_file(tmp_path):
    with pytest.raises(MediaError, match="не найден"):
        probe(tmp_path / "absent.mp4")


def test_probe_rejects_a_non_media_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("this is not audio", encoding="utf-8")
    with pytest.raises(MediaError):
        probe(path)


def test_media_error_separates_detail_from_message(tmp_path):
    """Driver output belongs in a log, not in front of the user."""
    path = tmp_path / "broken.mp4"
    path.write_bytes(b"\x00" * 64)
    with pytest.raises(MediaError) as caught:
        probe(path)
    assert "формат" in str(caught.value).lower()
    assert hasattr(caught.value, "detail")


# -- pipeline contracts --------------------------------------------------

def test_unknown_export_format_is_refused_before_transcribing(tmp_path):
    """Rejecting the format after ten minutes of GPU work would be rude."""
    from lt_core.pipeline.batch import transcribe_file

    path = tmp_path / "clip.wav"
    write_wav(path, 0.5)

    class ExplodingTranscriber:
        def transcribe(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("must not reach the model")

    with pytest.raises(ValueError, match="Неизвестный формат"):
        transcribe_file(path, ExplodingTranscriber(), formats=("srt", "docx"))


def test_this_build_offers_the_three_agreed_languages():
    from lt_core.asr.transcriber import SUPPORTED_LANGUAGES

    assert set(SUPPORTED_LANGUAGES) == {"ru", "en", "de"}


def test_unsupported_language_is_rejected_by_name():
    from lt_core.asr.transcriber import UnsupportedLanguage, Transcriber

    options_cls = __import__(
        "lt_core.asr.transcriber", fromlist=["TranscribeOptions"]
    ).TranscribeOptions

    # Constructed without loading a model: the check happens before inference.
    transcriber = Transcriber.__new__(Transcriber)
    with pytest.raises(UnsupportedLanguage, match="pl"):
        Transcriber.transcribe(transcriber, "x.wav", options_cls(language="pl"))


def test_yt_dlp_is_told_where_ffmpeg_is(tmp_path, monkeypatch):
    """The ffmpeg in use is imageio-ffmpeg's, on no PATH. Without being told,
    yt-dlp downloaded and then failed: «ffprobe and ffmpeg not found»."""
    import subprocess
    from pathlib import Path

    from lt_core import media

    seen: list[list[str]] = []
    monkeypatch.setattr(
        media.subprocess, "run",
        lambda command, **kw: seen.append(command) or subprocess.CompletedProcess(command, 1, "", ""),
    )
    with pytest.raises(media.MediaError):
        media.fetch_url("https://www.youtube.com/watch?v=zzOlFH0iD0k", tmp_path)
    command = seen[0]
    location = command[command.index("--ffmpeg-location") + 1]
    assert Path(location).is_file()


def test_yt_dlp_is_given_the_bundled_javascript_runtime(tmp_path, monkeypatch):
    """YouTube needs JavaScript run to list its formats; without a runtime a
    download occasionally failed outright."""
    import subprocess
    from pathlib import Path

    pytest.importorskip("deno")
    from lt_core import media

    seen: list[list[str]] = []
    monkeypatch.setattr(
        media.subprocess, "run",
        lambda command, **kw: seen.append(command) or subprocess.CompletedProcess(command, 1, "", ""),
    )
    with pytest.raises(media.MediaError):
        media.fetch_url("https://www.youtube.com/watch?v=zzOlFH0iD0k", tmp_path)
    command = seen[0]
    runtime = command[command.index("--js-runtimes") + 1]
    assert runtime.startswith("deno:")
    assert Path(runtime[len("deno:"):]).is_file()


def _scripted_run(monkeypatch, answers):
    """subprocess.run answering yt-dlp from a script of (code, stdout, stderr)."""
    import subprocess

    from lt_core import media

    calls: list[int] = []

    def run(command, **kwargs):
        index = min(len(calls), len(answers) - 1)
        calls.append(index)
        code, out, err = answers[index]
        return subprocess.CompletedProcess(command, code, out, err)

    monkeypatch.setattr(media.subprocess, "run", run)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return calls


def test_a_refused_download_is_tried_again(tmp_path, monkeypatch):
    """YouTube refuses, now and then, a request it served a second before."""
    from lt_core import media

    clip = tmp_path / "clip.wav"
    write_wav_file = __import__("wave").open(str(clip), "wb")
    write_wav_file.setnchannels(1)
    write_wav_file.setsampwidth(2)
    write_wav_file.setframerate(16000)
    write_wav_file.writeframes(b"\x00\x00" * 16000)
    write_wav_file.close()
    refused = (1, "", "ERROR: unable to download video data: HTTP Error 403: Forbidden")
    calls = _scripted_run(monkeypatch, [refused, (0, str(clip), "")])
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(
        path=clip, duration=1.0, title="clip", has_audio=True, has_video=False))
    info = media.fetch_url("https://www.youtube.com/watch?v=x", tmp_path)
    assert len(calls) == 2
    assert info.path == clip


def test_a_download_that_cannot_work_is_not_retried(tmp_path, monkeypatch):
    from lt_core import media

    calls = _scripted_run(monkeypatch, [(1, "", "ERROR: [youtube] x: Video unavailable")])
    with pytest.raises(media.MediaError):
        media.fetch_url("https://www.youtube.com/watch?v=x", tmp_path)
    assert len(calls) == 1


def test_a_refusal_is_given_up_on_after_three_tries(tmp_path, monkeypatch):
    from lt_core import media

    refused = (1, "", "ERROR: unable to download video data: HTTP Error 403: Forbidden")
    calls = _scripted_run(monkeypatch, [refused])
    with pytest.raises(media.MediaError):
        media.fetch_url("https://www.youtube.com/watch?v=x", tmp_path)
    assert len(calls) == 1 + media.REFUSAL_RETRIES
