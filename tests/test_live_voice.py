"""Reading the translation aloud must not stop the session from hearing."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from lt_core.audio.types import AudioChunk
from lt_ui import engine as engine_module
from lt_ui.store import Settings


class _Update:
    def __init__(self, text: str, audio_time: float) -> None:
        self.translation = text
        self.translation_language = "ru"
        self.speaker_language = ""
        self.audio_time = audio_time
        self.committed = text
        self.partial = ""
        self.has_content = True


# -- the worker keeps hearing ------------------------------------------------

class _Source:
    """Chunks as fast as they are taken, stamped with when they were taken."""

    def __init__(self, count: int) -> None:
        self.count = count
        self._stop = threading.Event()

    def stream(self):
        for n in range(self.count):
            if self._stop.is_set():
                return
            yield AudioChunk(np.zeros(512, np.float32), n * 0.032,
                             captured_at=time.monotonic())
            time.sleep(0.002)

    def stop(self):
        self._stop.set()


class _Session:
    """One translated line on the first chunk; afterwards, nothing."""

    fed_at: list[float] = []

    def __init__(self, *args, **kwargs) -> None:
        _Session.fed_at = []

    def feed(self, chunk):
        _Session.fed_at.append(time.monotonic())
        if len(_Session.fed_at) == 1:
            return _Update("Длинная фраза", chunk.end_time)
        return None

    def finish(self):
        class _Done:
            has_content = False
        return _Done()


def test_the_session_goes_on_hearing_while_a_line_is_read(monkeypatch):
    """It used to read each line itself and hear nothing meanwhile; on a
    fast speaker the eight-second capture queue overflowed and 13.8 s of a
    minute was dropped unheard."""
    spoken: list[tuple[float, float]] = []

    def slow_speak(speaker, text, gate, hurry=False, **kwargs):
        start = time.monotonic()
        time.sleep(0.5)
        spoken.append((start, time.monotonic()))
        return 0.5

    source = _Source(200)
    monkeypatch.setattr(engine_module, "default_device", lambda kind: object())
    from lt_core.audio.echo_gate import RoutingAdvice

    monkeypatch.setattr(engine_module, "check_routing", lambda d, p: RoutingAdvice(True, "test"))
    monkeypatch.setattr(engine_module, "open_source", lambda device: source)
    monkeypatch.setattr(engine_module, "Speaker", lambda *a, **k: type("V", (), {"voice_name": "v"})())
    monkeypatch.setattr(engine_module, "LiveSession", _Session)
    monkeypatch.setattr(engine_module, "_speak", slow_speak)

    worker = engine_module.LiveWorker(
        Settings(realtime_voice=True, capture_kind="system", to_lang="ru"),
        object(), object(),
    )
    worker.run()

    assert len(spoken) == 1
    start, end = spoken[0]
    heard_meanwhile = [t for t in _Session.fed_at if start < t < end]
    assert len(heard_meanwhile) > 20, "the session must keep taking audio while the voice speaks"
    assert worker.read_lines == 1


# -- the voice does not fall behind for ever ---------------------------------

def _reader(monkeypatch, clock_value):
    said: list[str] = []
    first = threading.Event()
    release = threading.Event()

    def fake_read(update, voices, gate, session, behind=0.0, *rest):
        said.append(update.translation)
        if not first.is_set():
            first.set()
            release.wait(2.0)
        return 1.0

    monkeypatch.setattr(engine_module, "_read_out", fake_read)
    clock = [clock_value]
    reader = engine_module._Reader({}, None, object(), clock=lambda: clock[0])
    return reader, said, first, release, clock


def test_a_stale_line_is_skipped_when_a_newer_one_waits(monkeypatch):
    reader, said, first, release, clock = _reader(monkeypatch, 1.0)
    reader.put(_Update("сейчас", 0.5))
    assert first.wait(2.0)
    clock[0] = 30.0
    reader.put(_Update("давно-1", 1.0))
    reader.put(_Update("давно-2", 2.0))
    reader.put(_Update("свежая", 29.5))
    release.set()
    reader.close()
    assert said == ["сейчас", "свежая"]
    assert reader.skipped == 2


def test_the_newest_line_is_read_however_late(monkeypatch):
    """Skipping exists to reach what is said now. The last line is what is
    said now, so it is read -- faster, not dropped. Caught in writing this:
    the stop marker behind it counted as a newer line, and the last thing
    said before stopping went unread."""
    reader, said, first, release, clock = _reader(monkeypatch, 50.0)
    release.set()
    reader.put(_Update("опоздала", 1.0))
    reader.close()
    assert said == ["опоздала"]
    assert reader.skipped == 0


def test_lines_are_read_in_the_order_they_were_said(monkeypatch):
    reader, said, first, release, clock = _reader(monkeypatch, 1.0)
    release.set()
    for n in range(5):
        reader.put(_Update(f"строка {n}", 1.0))
    reader.close()
    assert said == [f"строка {n}" for n in range(5)]


def test_a_line_without_a_translation_is_not_queued(monkeypatch):
    reader, said, first, release, clock = _reader(monkeypatch, 1.0)
    release.set()
    reader.put(_Update("", 1.0))
    reader.close()
    assert said == []
