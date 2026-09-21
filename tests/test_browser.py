"""The embedded browser: its audio reaches the live session, and nothing else.

What is tested here is the wiring that decides correctness -- which source a
live session reads, what is gated, which URL a typed line becomes, what the
page is told to run. Whether YouTube itself plays in QtWebEngine is measured
by spike/browser_probe.py and spike/adblock_probe.py against the real site,
not asserted here.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from lt_core.audio.capture import PageAudioSource
from lt_ui import engine as engine_module
from lt_ui.store import Settings


class _Done:
    has_content = False


class _QuietSession:
    """Takes audio, says nothing: the test is about what feeds it."""

    fed = 0

    def __init__(self, *args, **kwargs) -> None:
        pass

    def feed(self, chunk):
        _QuietSession.fed += chunk.samples.size
        return None

    def finish(self):
        return _Done()


def _forbidden(name):
    def refuse(*args, **kwargs):
        raise AssertionError(f"{name} must not be consulted for page audio")
    return refuse


def test_page_audio_needs_no_device_no_routing_check_and_no_echo_gate(monkeypatch):
    """With the translation read aloud, a loopback session refuses to share a
    device with the speakers and mutes itself while speaking. Page audio is
    the video's own sound, so neither applies -- and the gate, if it ran,
    would cut the video's speech out while the dub played."""
    monkeypatch.setattr(engine_module, "default_device", _forbidden("default_device"))
    monkeypatch.setattr(engine_module, "check_routing", _forbidden("check_routing"))
    monkeypatch.setattr(engine_module, "EchoGate", _forbidden("EchoGate"))
    monkeypatch.setattr(engine_module, "open_source", _forbidden("open_source"))
    monkeypatch.setattr(engine_module, "Speaker", lambda *a, **k: object())
    monkeypatch.setattr(engine_module, "LiveSession", _QuietSession)
    _QuietSession.fed = 0

    settings = Settings(realtime_voice=True, capture_kind="system")
    source = PageAudioSource()
    source.push(np.zeros(16_000, dtype=np.float32), 16_000)
    worker = engine_module.LiveWorker(settings, object(), object(), source=source)
    failures: list[str] = []
    worker.failed.connect(failures.append)

    threading.Timer(0.4, worker.request_stop).start()
    worker.run()

    assert failures == []
    assert _QuietSession.fed >= 15_000, "the page's audio must reach the session"


def test_without_a_source_the_device_is_still_asked_for(monkeypatch):
    """The browser's path must not have become everyone's."""
    asked: list[str] = []

    def no_device(kind):
        asked.append(kind)
        return None

    monkeypatch.setattr(engine_module, "default_device", no_device)
    monkeypatch.setattr(engine_module, "list_capture_devices", lambda: [])
    worker = engine_module.LiveWorker(Settings(capture_kind="system"), object(), object())
    failures: list[str] = []
    worker.failed.connect(failures.append)
    worker.run()
    assert asked == ["system"]
    assert failures, "no device is a refusal the user sees"


# -- the address bar -----------------------------------------------------

@pytest.mark.parametrize("typed,expected", [
    ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc"),
    ("youtube.com/watch?v=abc", "https://youtube.com/watch?v=abc"),
    ("ted.com", "https://ted.com"),
    ("localhost:8080/x", "https://localhost:8080/x"),
])
def test_an_address_is_opened_as_an_address(typed, expected):
    from lt_ui.browser import address_to_url

    assert address_to_url(typed).toString() == expected


@pytest.mark.parametrize("typed", ["ted talk creativity", "Sir Ken Robinson", "python"])
def test_anything_else_is_a_youtube_search(typed):
    """Finding a video is what this browser is for; a bare word is a query,
    not a host called «python»."""
    from lt_ui.browser import address_to_url

    url = address_to_url(typed)
    assert url.host() == "www.youtube.com"
    assert url.path() == "/results"
    assert typed.split()[0] in url.query(url.ComponentFormattingOption.FullyDecoded)


def test_an_empty_address_goes_nowhere():
    from lt_ui.browser import address_to_url

    assert address_to_url("   ") is None


# -- what the page hands over ---------------------------------------------

def _drain_json(pcm: np.ndarray, **state) -> str:
    import base64
    import json

    body = {"taps": 1, "rate": 48_000, "ad": False, "playing": True, "error": ""}
    body.update(state)
    body["pcm"] = base64.b64encode(pcm.astype(np.int16).tobytes()).decode()
    return json.dumps(body)


def test_the_drain_carries_pcm_as_the_page_packed_it():
    from lt_ui.browser import decode_drain

    pcm = np.array([0, 1000, -1000, 32767, -32768], dtype=np.int16)
    state, decoded = decode_drain(_drain_json(pcm))
    assert decoded.tolist() == pcm.tolist()
    assert state["rate"] == 48_000
    assert "pcm" not in state


class _FakePage:
    def __init__(self) -> None:
        self.ran: list[str] = []

        class _Signal:
            def connect(self, _slot):
                pass

        self.loadFinished = _Signal()

    def runJavaScript(self, script, world=None, callback=None):  # noqa: N802
        self.ran.append(script)


@pytest.fixture
def qapp():
    import sys

    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def test_a_drained_ad_gates_the_source_and_says_so(qapp):
    from lt_ui.browser import PageTap

    tap = PageTap(_FakePage())
    source = PageAudioSource()
    said: list[str] = []
    tap.state.connect(said.append)
    tap.start(source)
    tap._drained(_drain_json(np.ones(4800, np.int16), ad=True))
    assert source.gated
    assert said[-1] == "ad"
    tap._drained(_drain_json(np.ones(4800, np.int16), ad=False))
    assert not source.gated
    assert said[-1] == "listening"
    assert source._inbox.qsize() == 2, "the ad's audio still arrives, to keep time"
    tap.stop()


def test_a_stopped_tap_hands_nothing_over(qapp):
    """A drain answered after stop() must not reach a session that has ended."""
    from lt_ui.browser import PageTap

    tap = PageTap(_FakePage())
    source = PageAudioSource()
    tap.start(source)
    tap.stop()
    tap._drained(_drain_json(np.ones(4800, np.int16)))
    assert source._inbox.qsize() == 0


def test_the_tap_is_switched_on_in_the_page_and_off_again(qapp):
    from lt_ui.browser import PageTap

    page = _FakePage()
    tap = PageTap(page)
    tap.start(PageAudioSource())
    tap.stop()
    assert "lf.on = true" in page.ran[0]
    assert "lf.on = false" in page.ran[-1]


# -- ad blocking ----------------------------------------------------------

def test_the_youtube_ad_script_leaves_other_sites_alone():
    """It rewrites JSON.parse. On every other site that would be a stranger
    in the page for no reason."""
    from lt_ui.browser import YOUTUBE_ADS_JS

    guard = YOUTUBE_ADS_JS.index(r"youtube\.com")
    assert guard < YOUTUBE_ADS_JS.index("JSON.parse")


def test_the_youtube_ad_script_removes_every_field_the_player_reads_ads_from():
    from lt_ui.browser import YOUTUBE_ADS_JS

    for field in ("adPlacements", "playerAds", "adSlots"):
        assert field in YOUTUBE_ADS_JS


def test_filter_lists_are_fetched_with_a_browser_user_agent(tmp_path, monkeypatch):
    """easylist.to refuses Python's default User-Agent with 403 -- measured."""
    import urllib.request

    from lt_ui import browser

    agents: list[str] = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"||ads.example^\n"

    def fake_urlopen(request, timeout=None):
        agents.append(request.get_header("User-agent"))
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    lists = browser.fetch_filter_lists(tmp_path)
    assert len(lists) == len(browser.FILTER_LISTS)
    assert all(agent and "Mozilla" in agent for agent in agents)


def test_a_failed_download_keeps_the_list_it_had(tmp_path, monkeypatch):
    import os
    import urllib.request

    from lt_ui import browser

    old = tmp_path / "easylist.txt"
    old.write_text("||kept.example^\n", encoding="utf-8")
    os.utime(old, (0, 0))  # stale, so a refresh is attempted

    def offline(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    lists = browser.fetch_filter_lists(tmp_path)
    assert lists == [old]
    assert old.read_text(encoding="utf-8") == "||kept.example^\n"


def test_the_blocker_refuses_what_its_list_names(tmp_path):
    pytest.importorskip("adblock")
    from lt_ui.browser import build_blocker

    path = tmp_path / "list.txt"
    path.write_text("||ads.example^\n", encoding="utf-8")
    engine = build_blocker([path])
    assert engine.check_network_urls(
        "https://ads.example/banner.js", "https://news.example/", "script"
    ).matched
    assert not engine.check_network_urls(
        "https://cdn.example/app.js", "https://news.example/", "script"
    ).matched


# -- the video under the voice -------------------------------------------

def test_a_line_read_out_is_announced_before_and_after(monkeypatch):
    import sounddevice as sd

    heard: list[bool] = []

    class _Voice:
        def say(self, text):
            return np.ones(2205, dtype=np.float32), 22_050

    monkeypatch.setattr(sd, "play", lambda *a, **k: heard.append("play"))
    engine_module._speak(_Voice(), "Привет", None, announce=heard.append)
    assert heard == [True, "play", False]


def test_a_failed_line_still_brings_the_video_back_up(monkeypatch):
    """A ducked video that never comes back up is a broken player."""
    import sounddevice as sd

    heard: list[bool] = []

    class _Voice:
        def say(self, text):
            return np.ones(2205, dtype=np.float32), 22_050

    def broken(*args, **kwargs):
        raise RuntimeError("device gone")

    monkeypatch.setattr(sd, "play", broken)
    with pytest.raises(RuntimeError):
        engine_module._speak(_Voice(), "Привет", None, announce=heard.append)
    assert heard == [True, False]


def _levels(page) -> list[float]:
    import re

    return [
        float(m.group(1))
        for script in page.ran
        for m in [re.search(r"setTargetAtTime\(([\d.]+)", script)] if m
    ]


def _wait(qapp, seconds: float) -> None:
    import time as _time

    end = _time.monotonic() + seconds
    while _time.monotonic() < end:
        qapp.processEvents()
        _time.sleep(0.01)


def test_the_video_is_lowered_under_a_line_and_raised_after(qapp):
    from lt_core.tts.dub import DUCK_BRIDGE, DUCK_GAIN
    from lt_ui.browser import PageTap

    page = _FakePage()
    tap = PageTap(page)
    tap.start(PageAudioSource())
    tap.duck(True)
    assert _levels(page) == [pytest.approx(DUCK_GAIN, abs=1e-4)]
    tap.duck(False)
    _wait(qapp, DUCK_BRIDGE + 0.2)
    assert _levels(page)[-1] == 1.0
    tap.stop()


def test_lines_read_back_to_back_keep_the_video_down_between_them(qapp):
    """Coming up for a moment between two lines is a pump, not a pause."""
    from lt_core.tts.dub import DUCK_BRIDGE
    from lt_ui.browser import PageTap

    page = _FakePage()
    tap = PageTap(page)
    tap.start(PageAudioSource())
    tap.duck(True)
    tap.duck(False)
    _wait(qapp, DUCK_BRIDGE / 3)
    tap.duck(True)
    _wait(qapp, DUCK_BRIDGE + 0.2)
    assert 1.0 not in _levels(page)
    tap.stop()


def test_stopping_mid_line_gives_the_video_its_volume_back(qapp):
    from lt_ui.browser import PageTap

    page = _FakePage()
    tap = PageTap(page)
    tap.start(PageAudioSource())
    tap.duck(True)
    tap.stop()
    assert _levels(page)[-1] == 1.0


def test_the_tap_listens_before_the_volume_the_viewer_hears():
    """Ducking is for the viewer. If the copy were taken after the gain,
    every line read out would drop the next words to -18 dB for the
    recogniser too."""
    from lt_ui.browser import TAP_JS

    assert "src.connect(proc)" in TAP_JS
    assert "gain.connect(proc)" not in TAP_JS


# -- sites this engine cannot play ------------------------------------------

@pytest.mark.parametrize("url,plays", [
    ("https://www.youtube.com/watch?v=abc", True),
    ("https://x.com/someone/status/1", False),
    ("https://mobile.twitter.com/someone/status/1", False),
    ("https://twitter.com/someone", False),
    ("https://notx.com/video", True),
])
def test_sites_without_playable_video_are_known(url, plays):
    """X serves H.264 only and this web engine has none -- measured in
    spike/browser_probe.py. Those pages are sent to the download path."""
    from PySide6.QtCore import QUrl

    from lt_ui.browser import plays_here

    assert plays_here(QUrl(url)) is plays


@pytest.mark.parametrize("url,label", [
    ("https://www.youtube.com/watch?v=UF8uR6Z6KLc&t=10s", "youtube.com/watch?v=UF8uR6Z6KLc"),
    ("https://x.com/someone/status/1789", "x.com/…/1789"),
    ("https://ted.com/", "ted.com"),
    ("https://vimeo.com/123", "vimeo.com/123"),
])
def test_a_link_gets_a_short_caption(url, label):
    from lt_ui.screens.upload import link_label

    assert link_label(url) == label


def test_a_link_reaches_the_file_screen_as_the_string_it_is(qapp, tmp_path):
    """A Path would make «https://x.com/…» into «https:» plus backslashes on
    Windows, and yt-dlp would be handed a file name that does not exist."""
    from lt_ui.store import Store
    from lt_ui.window import Window

    window = Window(Store(tmp_path))
    url = "https://x.com/someone/status/1789"
    window.translate_link(url)
    assert window.current_screen == "upload"
    assert window._upload._path == url
    assert isinstance(window._upload._path, str)
    window.close()


def test_the_browser_remembers_where_it_was(qapp, tmp_path):
    from PySide6.QtCore import QUrl

    from lt_ui.store import Store
    from lt_ui.window import Window

    window = Window(Store(tmp_path))
    window._browser._show_url(QUrl("https://www.youtube.com/watch?v=abc"))
    window.close()
    assert Store(tmp_path).settings.browser_url == "https://www.youtube.com/watch?v=abc"
