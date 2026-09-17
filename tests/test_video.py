"""Day 7: a copy of the video with the translated soundtrack against it.

These run ffmpeg. It is bundled with the project, so this is the same binary
the product uses rather than a stand-in -- and the bug recorded below was one
only ffmpeg itself would have shown.
"""

from __future__ import annotations

import subprocess
import wave

import numpy as np
import pytest

from lt_core.audio.dshow import ffmpeg_path
from lt_core.media import probe
from lt_core.video.mux import MuxError, container_for, replace_audio

VIDEO_SECONDS = 3.0
DUB_SECONDS = 5.0
#: Deliberately shorter than the picture: this is the shape of the bug.
LAST_CAPTION_END = 1.5


def write_tone(path, seconds: float, rate: int = 16_000) -> None:
    t = np.arange(int(seconds * rate)) / rate
    samples = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())


@pytest.fixture(scope="module")
def source_video(tmp_path_factory):
    """A short video with its own soundtrack."""
    folder = tmp_path_factory.mktemp("video")
    path = folder / "clip.mp4"
    completed = subprocess.run(
        [
            ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=25:duration={VIDEO_SECONDS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={VIDEO_SECONDS}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        capture_output=True, text=True, timeout=120,
    )
    if completed.returncode != 0 or not path.exists():
        pytest.skip(f"ffmpeg could not build a fixture: {completed.stderr[-200:]}")
    return path


@pytest.fixture(scope="module")
def dub_audio(tmp_path_factory):
    path = tmp_path_factory.mktemp("dub") / "voice.wav"
    write_tone(path, DUB_SECONDS)
    return path


@pytest.fixture(scope="module")
def captions(tmp_path_factory):
    path = tmp_path_factory.mktemp("subs") / "voice.srt"
    path.write_text(
        "1\n00:00:00,200 --> 00:00:01,500\nпервая строка\n\n",
        encoding="utf-8",
    )
    return path


def streams_of(path) -> str:
    completed = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    return completed.stderr


# -- the point of the feature -------------------------------------------

def test_the_translated_track_comes_first_and_the_original_rides_along(
    source_video, dub_audio, tmp_path
):
    result = replace_audio(
        source_video, dub_audio, tmp_path / "out",
        target_language="ru", source_language="en",
    )
    assert result.path.exists()
    assert result.kept_original

    report = streams_of(result.path)
    assert report.count(": Audio:") == 2
    # The translation is the track a player picks up without being asked.
    assert "(rus): Audio" in report
    assert "(eng): Audio" in report
    assert report.index("(rus): Audio") < report.index("(eng): Audio")


def test_the_picture_is_copied_not_re_encoded(source_video, dub_audio, tmp_path):
    """The whole reason this is fast. A re-encode would also lose quality."""
    result = replace_audio(source_video, dub_audio, tmp_path / "out")
    before = streams_of(source_video)
    after = streams_of(result.path)
    assert "Video: h264" in before and "Video: h264" in after
    assert "320x180" in after


def test_the_original_can_be_left_out(source_video, dub_audio, tmp_path):
    result = replace_audio(
        source_video, dub_audio, tmp_path / "out", keep_original=False
    )
    assert not result.kept_original
    assert streams_of(result.path).count(": Audio:") == 1


def test_subtitles_ride_along_as_a_track(
    source_video, dub_audio, captions, tmp_path
):
    result = replace_audio(
        source_video, dub_audio, tmp_path / "out",
        target_language="ru", subtitles=captions,
    )
    assert result.with_subtitles
    assert ": Subtitle:" in streams_of(result.path)


# -- the bug this cost -------------------------------------------------

def test_adding_subtitles_does_not_shorten_the_video(
    source_video, dub_audio, captions, tmp_path
):
    """`-shortest` ends the output when the *subtitle* stream ends.

    Measured on a real file: a 105.7 s video whose last caption closed at
    103.7 s came out 103.7 s long -- two seconds of picture silently dropped
    by adding a subtitle track. The picture's own length is asked for
    instead.
    """
    result = replace_audio(
        source_video, dub_audio, tmp_path / "out",
        target_language="ru", subtitles=captions,
        duration=probe(source_video).duration,
    )
    assert probe(result.path).duration == pytest.approx(VIDEO_SECONDS, abs=0.15)
    assert probe(result.path).duration > LAST_CAPTION_END * 1.5


def test_a_dub_longer_than_the_picture_does_not_extend_it(
    source_video, dub_audio, tmp_path
):
    """The soundtrack is padded past the end; the picture decides the length."""
    result = replace_audio(
        source_video, dub_audio, tmp_path / "out",
        duration=probe(source_video).duration,
    )
    assert probe(result.path).duration == pytest.approx(VIDEO_SECONDS, abs=0.15)


def test_the_length_is_found_on_its_own_when_not_given(
    source_video, dub_audio, captions, tmp_path
):
    """A caller that does not know the duration still gets a whole video."""
    result = replace_audio(
        source_video, dub_audio, tmp_path / "out", subtitles=captions
    )
    assert probe(result.path).duration == pytest.approx(VIDEO_SECONDS, abs=0.15)


def test_the_language_tag_survives_the_container_being_added(
    source_video, dub_audio, tmp_path
):
    """`with_suffix` treats «.ru» as a suffix and replaces it.

    The pipeline names its output «<stem>.<language>», so the obvious call
    turned «talk.ru» into «talk.mp4» -- the language gone, and, since file
    mode writes beside the source by default, the same name as the source
    video it was made from.
    """
    result = replace_audio(
        source_video, dub_audio, tmp_path / "talk.ru", target_language="ru"
    )
    assert result.path.name == "talk.ru.mp4"


def test_a_translation_is_never_written_over_its_own_source(
    source_video, dub_audio
):
    """The input is the one file that cannot be replaced."""
    with pytest.raises(MuxError, match="совпало бы"):
        replace_audio(source_video, dub_audio, source_video)


def test_a_destination_that_already_names_a_container_is_left_alone(
    source_video, dub_audio, tmp_path
):
    result = replace_audio(source_video, dub_audio, tmp_path / "out.mp4")
    assert result.path.name == "out.mp4"


# -- containers and refusals -------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("film.mkv", ".mkv"), ("clip.mov", ".mov"), ("talk.mp4", ".mp4"),
    ("recording.avi", ".mp4"), ("voice.m4a", ".mp4"),
])
def test_an_unsupported_container_is_written_as_mp4(name, expected, tmp_path):
    assert container_for(tmp_path / name) == expected


def test_a_missing_video_is_refused_by_name(dub_audio, tmp_path):
    with pytest.raises(MuxError, match="не найдено"):
        replace_audio(tmp_path / "absent.mp4", dub_audio, tmp_path / "out")


def test_a_missing_soundtrack_is_refused_by_name(source_video, tmp_path):
    with pytest.raises(MuxError, match="не найдена"):
        replace_audio(source_video, tmp_path / "absent.wav", tmp_path / "out")


# -- what has a picture at all -----------------------------------------

def test_a_video_is_recognised_as_one(source_video):
    info = probe(source_video)
    assert info.has_video and info.has_audio


def test_audio_only_files_are_not_offered_a_video_copy(tmp_path):
    """Otherwise the pipeline would try to mux a soundtrack onto nothing."""
    path = tmp_path / "speech.wav"
    write_tone(path, 1.0)
    assert not probe(path).has_video
