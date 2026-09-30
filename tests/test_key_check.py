"""Checking a key must not freeze the window, and must not blame the key.

A user reported that the service "rejects" their NVIDIA key, and generated
two new ones before asking. Measured against the real endpoint with their
own key: `GET /models` answered 200 and listed 81 models, so the key was
never the problem. What actually happens on that free tier, five identical
one-word requests in a row: 35 s, 9 s, no answer in 90 s, 70 s, 38 s.

The check ran on the interface thread with a 300 s timeout, so Windows
painted the window grey and labelled it "not responding" -- which is what
the screenshot showed. And the failures it does produce were reported in
the two most misleading ways available: a model the account may not call
came back as "the service rejected your key", and a read that timed out
came back as "check your internet".
"""

from __future__ import annotations

import io
import sys
import urllib.error

import pytest

from lt_core.mt import cloud
from lt_core.mt.types import TranslationError


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUAFLOW_DATA", str(tmp_path / "profile"))
    from lt_core.runtime import bootstrap
    from lt_ui.store import MODEL_ROOT, Store
    from lt_ui.window import Window

    bootstrap(MODEL_ROOT)
    return Window(Store(tmp_path / "state"))


def _raises(error):
    def urlopen(request, timeout=None):
        raise error
    return urlopen


def _http(code: int, body: str):
    return urllib.error.HTTPError(
        "https://example.invalid/v1/chat/completions", code, "no",
        {}, io.BytesIO(body.encode("utf-8")),
    )


PAYLOAD = {"model": "google/gemma-4-31b-it", "messages": []}


# -- what the service said, and what the user is told -------------------

def test_a_model_the_account_cannot_call_is_not_the_key_s_fault(monkeypatch):
    """NVIDIA lists models it will not serve, and answers 404 for them."""
    body = ('{"status":404,"title":"Not Found","detail":"Function '
            '\'ee47df99\': Not found for account \'exiqEsS9\'"}')
    monkeypatch.setattr(cloud.urllib.request, "urlopen", _raises(_http(404, body)))

    with pytest.raises(TranslationError) as caught:
        cloud._post("https://example.invalid/v1/chat/completions",
                    PAYLOAD, {}, 30.0)

    said = str(caught.value)
    assert "gemma-4-31b-it" in said, "the message has to name the model"
    assert "ключ" in said.lower(), "and say plainly that the key is not at fault"
    assert "отклонил ключ" not in said


def test_a_retired_model_says_so(monkeypatch):
    body = ('{"status":410,"detail":"The model has reached its end of life"}')
    monkeypatch.setattr(cloud.urllib.request, "urlopen", _raises(_http(410, body)))

    with pytest.raises(TranslationError) as caught:
        cloud._post("https://example.invalid/v1/chat/completions",
                    PAYLOAD, {}, 30.0)
    assert "gemma-4-31b-it" in str(caught.value)


def test_a_key_that_really_is_refused_still_says_so(monkeypatch):
    monkeypatch.setattr(cloud.urllib.request, "urlopen",
                        _raises(_http(401, '{"detail":"invalid key"}')))
    with pytest.raises(TranslationError) as caught:
        cloud._post("https://example.invalid/v1", PAYLOAD, {}, 30.0)
    assert "отклонил ключ" in str(caught.value)


def test_a_read_that_never_finishes_is_not_a_missing_internet(monkeypatch):
    """The wrong half of this sends someone to look at their router."""
    monkeypatch.setattr(cloud.urllib.request, "urlopen", _raises(TimeoutError()))

    with pytest.raises(TranslationError) as caught:
        cloud._post("https://example.invalid/v1", PAYLOAD, {}, 45.0)

    said = str(caught.value)
    assert "45" in said, "the message says how long it waited"
    assert "интернет" not in said.lower()


def test_a_connect_timeout_reads_the_same_way(monkeypatch):
    monkeypatch.setattr(
        cloud.urllib.request, "urlopen",
        _raises(urllib.error.URLError(TimeoutError())),
    )
    with pytest.raises(TranslationError) as caught:
        cloud._post("https://example.invalid/v1", PAYLOAD, {}, 45.0)
    assert "интернет" not in str(caught.value).lower()


def test_a_genuinely_unreachable_service_still_mentions_the_connection(monkeypatch):
    monkeypatch.setattr(
        cloud.urllib.request, "urlopen",
        _raises(urllib.error.URLError(ConnectionRefusedError())),
    )
    with pytest.raises(TranslationError) as caught:
        cloud._post("https://example.invalid/v1", PAYLOAD, {}, 45.0)
    assert "интернет" in str(caught.value).lower()


# -- the window stays alive --------------------------------------------

def test_the_check_does_not_run_on_the_interface_thread(window, monkeypatch):
    """The whole point: a slow service must not grey out the window."""
    from PySide6.QtCore import QThread

    from lt_ui.screens.settings import _KeyCheck

    assert issubclass(_KeyCheck, QThread)

    screen = window._settings
    window.store.settings.shorten_with = "nvidia"
    # The field holds the key: pressing the button saves what is in it first,
    # exactly as it does for a person who just typed one.
    screen._key.setText("nvapi-pretend")

    started: list = []
    monkeypatch.setattr(_KeyCheck, "start", lambda self: started.append(self))

    screen._check_key()
    assert started, "the check has to be handed to a thread, not run here"
    assert isinstance(started[0], QThread)


def test_the_check_has_a_timeout_a_person_will_sit_through():
    from lt_ui.screens.settings import _KeyCheck

    assert 15 <= _KeyCheck.TIMEOUT <= 90, (
        "long enough for a slow free tier, short enough not to look hung"
    )


def test_a_second_press_does_not_start_a_second_check(window, monkeypatch):
    from lt_ui.screens.settings import _KeyCheck

    screen = window._settings
    window.store.settings.shorten_with = "nvidia"
    screen._key.setText("nvapi-pretend")

    monkeypatch.setattr(_KeyCheck, "start", lambda self: None)
    monkeypatch.setattr(_KeyCheck, "isRunning", lambda self: True)

    screen._check_key()
    first = screen._checker
    screen._check_key()
    assert screen._checker is first, "one check at a time"


def test_the_wait_is_reported_rather_than_left_blank(window):
    screen = window._settings
    screen._waited.start()
    screen._tick_waiting()
    assert "…" in screen._key_note.text() or "с." in screen._key_note.text()


def test_a_failed_check_shows_what_the_service_said(window):
    screen = window._settings
    screen._checked(False, "Модель «x» недоступна для этого ключа")
    assert "недоступна" in screen._key_note.text()
    assert not screen._waiting.isActive()


def test_a_good_check_says_how_long_it_took(window):
    screen = window._settings
    screen._waited.start()
    screen._checked(True, "")
    assert "Ключ работает" in screen._key_note.text()
