"""A live session that hears nothing says so.

Reported from use, angrily: a whole conference call came out as nothing
translated, with «Слушаю…» on the screen the entire time. The capture was
the microphone and the call was coming out of the speakers, so the device
was open, on time and empty -- which on screen is indistinguishable from a
room where nobody happens to be speaking.
"""

from __future__ import annotations

import sys
import threading
import time

import numpy as np
import pytest
from PySide6.QtCore import Qt

from lt_core.audio.capture import PageAudioSource
from lt_ui import engine as engine_module
from lt_ui.store import Settings


class _QuietSession:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def feed(self, chunk):
        return None

    def finish(self):
        return []


def _worker(monkeypatch, source, **settings):
    monkeypatch.setattr(engine_module, "default_device", lambda kind: None)
    monkeypatch.setattr(engine_module, "check_routing", lambda *a, **k: None)
    monkeypatch.setattr(engine_module, "EchoGate", lambda *a, **k: None)
    monkeypatch.setattr(engine_module, "LiveSession", _QuietSession)
    monkeypatch.setattr(engine_module, "DEAF_AFTER", 0.15)
    worker = engine_module.LiveWorker(
        Settings(**settings), object(), object(), source=source)
    said: list[tuple[bool, str]] = []
    # Direct, because the silence is noticed on its own thread and this test
    # runs the worker in place, with no event loop to deliver a queued call.
    worker.hearing.connect(lambda ok, name: said.append((ok, name)),
                           Qt.DirectConnection)
    return worker, said


#: One block of the plan, in wall-clock terms.
_STEP = 0.05


def _feed(source: PageAudioSource, plan: list[tuple[float, float]]) -> threading.Thread:
    """Push blocks at roughly real time.

    Pushing a second of samples in one go is a second of *audio* and no time
    at all, which is not what a device does and not what the silence is
    measured against.
    """

    def run() -> None:
        for seconds, level in plan:
            for _ in range(max(1, round(seconds / _STEP))):
                source.push(
                    np.full(int(16_000 * _STEP), level, dtype=np.float32), 16_000)
                time.sleep(_STEP)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_a_session_that_hears_nothing_says_so(monkeypatch):
    source = PageAudioSource()
    _feed(source, [(1.2, 0.0)])
    worker, said = _worker(monkeypatch, source, capture_kind="microphone")
    threading.Timer(1.0, worker.request_stop).start()
    worker.run()
    assert said and said[0][0] is False, f"it never admitted to silence: {said}"


def test_sound_arriving_takes_it_back(monkeypatch):
    source = PageAudioSource()
    _feed(source, [(0.5, 0.0), (0.8, 0.3)])
    worker, said = _worker(monkeypatch, source, capture_kind="microphone")
    threading.Timer(1.2, worker.request_stop).start()
    worker.run()
    assert [ok for ok, _name in said][:2] == [False, True], said


def test_a_session_that_hears_speech_never_complains(monkeypatch):
    source = PageAudioSource()
    _feed(source, [(1.2, 0.3)])
    worker, said = _worker(monkeypatch, source, capture_kind="system")
    threading.Timer(1.0, worker.request_stop).start()
    worker.run()
    assert said == [], said


def test_the_floor_is_below_speech_and_above_a_dead_line():
    """Room tone on an open microphone sits well under it; a dead line is
    zero. Measured on this machine: a loopback with a call playing peaked at
    0.29, a device delivering nothing peaked at 0.0."""
    assert 0.0 < engine_module.HEARING_FLOOR < 0.1


# -- what the screen does with it ----------------------------------------

@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def _screen(app, tmp_path):
    from lt_core.runtime import bootstrap
    from lt_ui.store import MODEL_ROOT, Store
    from lt_ui.window import Window

    bootstrap(MODEL_ROOT)
    window = Window(Store(tmp_path / "state"))
    screen = window._realtime
    screen._mine = True
    return window, screen


def test_on_a_microphone_it_names_the_switch_that_would_help(app, tmp_path):
    window, screen = _screen(app, tmp_path)
    try:
        window.store.settings.capture_kind = "microphone"
        screen._on_hearing(False, "Микрофон (Realtek)")
        shown = screen._status.text()
        assert "Микрофон (Realtek)" in shown, "it must say which device is quiet"
        assert "Звук системы" in shown, "on a call that is the answer"
    finally:
        window.close()


def test_on_system_sound_it_says_something_else(app, tmp_path):
    window, screen = _screen(app, tmp_path)
    try:
        window.store.settings.capture_kind = "system"
        screen._on_hearing(False, "Динамики")
        shown = screen._status.text()
        assert "Динамики" in shown
        assert "Звук системы" not in shown, "it is already on system sound"
    finally:
        window.close()


def test_when_sound_comes_back_it_goes_back_to_listening(app, tmp_path):
    window, screen = _screen(app, tmp_path)
    try:
        screen._on_hearing(False, "Микрофон")
        screen._on_hearing(True, "Микрофон")
        assert screen._status.text() == "Слушаю…"
    finally:
        window.close()
