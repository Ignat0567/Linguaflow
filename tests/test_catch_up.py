"""Catching up: the video waits for its translation instead of losing words."""

from __future__ import annotations

import sys
import time

import numpy as np
import pytest

from lt_core.audio.capture import PageAudioSource


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def _wait(qapp, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)


class _Target:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def hold(self, held: bool) -> None:
        self.calls.append(held)


def _catch(qapp, **timing):
    from lt_ui.browser import CatchUp

    target = _Target()
    catch = CatchUp(target)
    for name, value in timing.items():
        setattr(catch, name, value)
    return catch, target


def test_an_ordinary_line_does_not_stop_the_video(qapp):
    """The voice is always a little behind; a three-second line read with no
    queue in front of it is not a backlog."""
    catch, target = _catch(qapp)
    catch.line_lag(3.0)
    catch.line_lag(catch.PAUSE_AT)
    assert target.calls == []


def test_a_backlog_holds_the_video(qapp):
    catch, target = _catch(qapp)
    catch.line_lag(catch.PAUSE_AT + 0.5)
    assert target.calls == [True]
    assert catch.holding
    catch.line_lag(9.0)
    assert target.calls == [True], "held once, not once per line"


def test_the_video_goes_on_once_the_voice_has_gone_quiet(qapp):
    catch, target = _catch(qapp, RESUME_AFTER=0.1)
    catch.line_lag(9.0)
    catch.speaking(True)
    catch.speaking(False)
    _wait(qapp, 0.2)
    assert target.calls == [True, False]
    assert not catch.holding


def test_the_next_queued_line_keeps_it_held(qapp):
    """Between two lines of a backlog the voice is quiet for a moment; going
    on there would restart the very pile-up the hold is for."""
    catch, target = _catch(qapp, RESUME_AFTER=0.15)
    catch.line_lag(9.0)
    catch.speaking(False)
    _wait(qapp, 0.05)
    catch.speaking(True)
    _wait(qapp, 0.25)
    assert target.calls == [True]
    catch.speaking(False)
    _wait(qapp, 0.25)
    assert target.calls == [True, False]


def test_a_stuck_session_never_leaves_the_video_stopped(qapp):
    catch, target = _catch(qapp, MAX_HOLD=0.1)
    catch.line_lag(9.0)
    catch.speaking(True)  # and never False
    _wait(qapp, 0.2)
    assert target.calls == [True, False]


def test_switched_off_it_never_holds(qapp):
    catch, target = _catch(qapp)
    catch.enabled = False
    catch.line_lag(30.0)
    assert target.calls == []


# -- the clock while held --------------------------------------------------

def test_a_held_source_makes_up_no_silence():
    """Made-up silence would fill the capture queue and push out the audio
    not yet recognised -- the words the pause exists to keep."""
    source = PageAudioSource()
    source.start()
    try:
        source.hold(True)
        time.sleep(source.SILENCE_AFTER + 0.5)
        assert source.silence_blocks == 0
    finally:
        source.stop()


def test_released_the_clock_does_not_count_the_pause():
    source = PageAudioSource()
    source.start()
    try:
        source.hold(True)
        time.sleep(source.SILENCE_AFTER + 0.3)
        source.hold(False)
        time.sleep(0.3)
        assert source.silence_blocks == 0, "the paused seconds are not owed as silence"
    finally:
        source.stop()


# -- what is held, and what is let go --------------------------------------

def test_the_page_releases_only_what_it_paused():
    from lt_ui.browser import HOLD_JS, RELEASE_JS

    assert "if (!v.paused)" in HOLD_JS and "__lfHeld = true" in HOLD_JS
    assert "if (v.__lfHeld)" in RELEASE_JS


def test_a_video_the_viewer_paused_is_not_started_by_the_release(qapp):
    from pathlib import Path

    from lt_ui.video_player import DownloadedVideo

    video = DownloadedVideo()
    video.load(Path("missing.mp4"), np.zeros((4800, 2), np.int16), 48_000, "t")
    started: list[bool] = []
    video.play = lambda: started.append(True)
    video.hold(True)   # nothing playing: nothing held
    video.hold(False)
    assert started == []
    video.stop()


def test_the_worker_reports_the_lag_at_the_end_of_the_line(monkeypatch):
    from lt_core.tts.speaker import Playback
    from lt_ui import engine as engine_module

    class _Voice:
        voice_name = "v"

    class _Update:
        translation = "Привет"
        translation_language = "ru"
        speaker_language = ""
        audio_time = 10.0

    def speak(*args, before=None, **kwargs):
        if before is not None:
            before(2.0)  # the line, synthesised, is two seconds long
        return 2.0

    monkeypatch.setattr(engine_module, "_speak", speak)
    playback = Playback()
    playback.until = 14.5
    reported: list[float] = []
    engine_module._read_out(_Update(), {"ru": _Voice()}, None, object(), playback,
                            None, reported.append)
    # Waited 4.5 s for the voice, then two seconds of its own: by its end
    # the reading trails by 6.5.
    assert reported == [pytest.approx(6.5)]


def test_the_video_waits_until_the_captured_audio_has_been_heard(qapp):
    """Measured: going on as soon as the voice stopped paused the video again
    0.6 s later -- the next line was already queued in the audio."""
    backlog = [3.0]
    from lt_ui.browser import CatchUp

    target = _Target()
    catch = CatchUp(target, backlog=lambda: backlog[0])
    catch.RESUME_AFTER = 0.1
    catch.line_lag(9.0)
    catch.speaking(False)
    _wait(qapp, 0.25)
    assert target.calls == [True], "audio still waiting: stay held"
    backlog[0] = 0.1
    _wait(qapp, 0.25)
    assert target.calls == [True, False]
