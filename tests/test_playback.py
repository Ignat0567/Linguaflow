"""Playing a downloaded video's sound ourselves, as the clock for its picture."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from lt_core.audio.playback import FilePlayback


class _Stream:
    def __init__(self, rate, channels, callback) -> None:
        self.callback = callback
        self.started = 0
        self.stopped = 0
        self.closed = False

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def close(self):
        self.closed = True


def _player(seconds=1.0, rate=48_000, value=16384, on_audio=None):
    frames = np.full((int(seconds * rate), 2), value, dtype=np.int16)
    streams: list[_Stream] = []

    def factory(r, c, cb):
        streams.append(_Stream(r, c, cb))
        return streams[-1]

    return FilePlayback(frames, rate, on_audio=on_audio, stream_factory=factory), streams


def _pull(player, n):
    out = np.zeros((n, player.channels), dtype=np.float32)
    player._callback(out, n)
    return out


def test_the_clock_is_what_has_been_played():
    player, _ = _player()
    player.play()
    _pull(player, 4800)
    _pull(player, 4800)
    assert player.position == pytest.approx(0.2)


def test_the_recogniser_hears_the_video_before_its_volume():
    """Lowered under a translation, the video must still reach recognition
    at full level -- otherwise every line read out would cost the next one."""
    heard: list[np.ndarray] = []
    player, _ = _player(on_audio=lambda samples, rate: heard.append(samples))
    player.play()
    player.set_volume(0.125)
    player._gain = 0.125  # already arrived
    out = _pull(player, 4800)
    assert np.allclose(heard[0], 0.5)
    assert np.allclose(out, 0.5 * 0.125)


def test_the_volume_moves_without_a_click():
    """A step from full to -18 dB in one sample is a click; the file dub
    fades over 150 ms and so does this."""
    player, _ = _player()
    player.play()
    player.set_volume(0.125)
    out = _pull(player, 480)  # 10 ms
    left = out[:, 0] / 0.5
    assert left[0] == pytest.approx(1.0)
    assert left[-1] > 0.9, "10 ms into a 150 ms fade is barely begun"
    assert np.all(np.diff(left) <= 1e-6)
    for _ in range(20):
        out = _pull(player, 480)
    assert out[-1, 0] / 0.5 == pytest.approx(0.125, abs=1e-3)


def test_seeking_moves_the_clock():
    player, _ = _player(seconds=10)
    player.seek(4.5)
    assert player.position == pytest.approx(4.5)
    player.seek(99)
    assert player.position == pytest.approx(10.0)


def test_the_end_of_the_soundtrack_is_silence_and_says_so():
    player, _ = _player(seconds=0.1)
    player.play()
    out = _pull(player, 9600)
    assert np.all(out[4800:] == 0)
    assert player.finished.is_set()
    assert not player.playing


def test_pause_and_play_keep_one_stream():
    player, streams = _player()
    player.play()
    player.pause()
    player.play()
    assert len(streams) == 1
    assert streams[0].started == 2 and streams[0].stopped == 1
    player.close()
    assert streams[0].closed


def test_the_soundtrack_of_an_h264_video_is_decoded(tmp_path):
    """The whole point: a file the web engine cannot play."""
    import imageio_ffmpeg

    from lt_core.media import decode_audio

    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         str(clip)],
        check=True, capture_output=True,
    )
    frames = decode_audio(clip, rate=48_000, channels=2)
    assert frames.shape[1] == 2
    assert abs(len(frames) / 48_000 - 2.0) < 0.1
    assert np.abs(frames).max() > 1000


def test_a_file_without_sound_is_a_readable_error(tmp_path):
    from lt_core.media import MediaError, decode_audio

    broken = tmp_path / "broken.mp4"
    Path(broken).write_bytes(b"not a video")
    with pytest.raises(MediaError):
        decode_audio(broken)
