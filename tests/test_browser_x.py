"""Sites the web engine cannot play: the signed-in download and our own player."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QUrl


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


# -- who the browser says it is ----------------------------------------------

def test_the_browser_introduces_itself_as_the_chrome_it_is():
    from lt_ui.browser import plain_user_agent

    agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) QtWebEngine/6.11.2 Chrome/134.0.6998.208 Safari/537.36"
    )
    plain = plain_user_agent(agent)
    assert "QtWebEngine" not in plain
    assert "Chrome/134.0.6998.208" in plain
    assert "  " not in plain


# -- the signed-in session, and only that one ----------------------------------

_COOKIES = [
    (".x.com", "/", True, 1893456000, "auth_token", "SECRET-X"),
    ("x.com", "/i", True, 0, "ct0", "csrf"),
    (".twitter.com", "/", True, 1893456000, "guest_id", "g1"),
    (".google.com", "/", True, 1893456000, "SID", "SECRET-GOOGLE"),
    (".notx.com", "/", False, 0, "other", "nope"),
]


def test_a_download_from_x_carries_x_and_nothing_else():
    """The file hands a session to another program. Every other site
    signed into here is none of its business."""
    from lt_ui.browser import netscape_cookies, site_hosts

    text = netscape_cookies(_COOKIES, site_hosts(QUrl("https://x.com/a/status/1")))
    assert "SECRET-X" in text and "csrf" in text and "g1" in text
    assert "SECRET-GOOGLE" not in text
    assert "nope" not in text, "notx.com only ends in the same letters"


def test_the_cookie_file_is_the_format_yt_dlp_reads():
    from lt_ui.browser import netscape_cookies

    text = netscape_cookies(_COOKIES[:2], ("x.com",))
    lines = text.splitlines()
    assert lines[0] == "# Netscape HTTP Cookie File"
    assert lines[1].split("\t") == [
        ".x.com", "TRUE", "/", "TRUE", "1893456000", "auth_token", "SECRET-X",
    ]
    assert lines[2].split("\t")[:2] == ["x.com", "FALSE"]


@pytest.mark.parametrize("url,hosts", [
    ("https://mobile.twitter.com/a", ("x.com", "twitter.com")),
    ("https://www.youtube.com/watch?v=1", ("youtube.com",)),
])
def test_one_site_under_two_names_shares_its_session(url, hosts):
    from lt_ui.browser import site_hosts

    assert site_hosts(QUrl(url)) == hosts


def test_yt_dlp_is_given_the_cookies(tmp_path, monkeypatch):
    import subprocess

    from lt_core import media

    seen: list[list[str]] = []

    def fake_run(command, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 1, "", "no")

    monkeypatch.setattr(media.subprocess, "run", fake_run)
    cookies = tmp_path / "c.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    with pytest.raises(media.MediaError):
        media.fetch_url("https://x.com/a/status/1", tmp_path, want_video=True, cookies=cookies)
    command = seen[0]
    assert command[command.index("--cookies") + 1] == str(cookies.resolve())


def test_without_a_session_yt_dlp_gets_no_cookie_flag(tmp_path, monkeypatch):
    import subprocess

    from lt_core import media

    seen: list[list[str]] = []
    monkeypatch.setattr(
        media.subprocess, "run",
        lambda command, **kw: seen.append(command) or subprocess.CompletedProcess(command, 1, "", ""),
    )
    with pytest.raises(media.MediaError):
        media.fetch_url("https://x.com/a/status/1", tmp_path)
    assert "--cookies" not in seen[0]


def test_the_session_file_is_removed_after_the_download(qapp, tmp_path, monkeypatch):
    """Even when the download fails: a session left on disk is a session
    anyone who finds the file can use."""
    from lt_core.media import MediaError
    from lt_ui import video_player

    def refuse(*args, **kwargs):
        raise MediaError("private post")

    monkeypatch.setattr(video_player, "fetch_url", refuse)
    cookies = tmp_path / "download-cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    worker = video_player.DownloadWorker("https://x.com/a/status/1", tmp_path, cookies)
    failures: list[str] = []
    worker.failed.connect(failures.append)
    worker.run()
    assert failures == ["private post"]
    assert not cookies.exists()


# -- the downloaded video under the voice --------------------------------------

def test_the_downloaded_video_steps_down_under_a_line(qapp):
    from lt_core.tts.dub import DUCK_GAIN
    from lt_ui.video_player import DownloadedVideo

    video = DownloadedVideo()
    video.load(Path("missing.mp4"), np.zeros((4800, 2), np.int16), 48_000, "t")
    video.duck(True)
    assert video.sound.volume == pytest.approx(DUCK_GAIN)
    video.duck(False)
    assert video._restore.isActive(), "back up after the bridge, not at once"
    video.stop()


def test_the_downloaded_video_is_heard_by_the_session_it_feeds(qapp):
    from lt_core.audio.capture import PageAudioSource
    from lt_ui.video_player import DownloadedVideo

    source = PageAudioSource()
    video = DownloadedVideo()
    frames = np.full((4800, 2), 8192, np.int16)
    video.load(Path("missing.mp4"), frames, 48_000, "t", on_audio=source.push)
    out = np.zeros((4800, 2), np.float32)
    video.sound._callback(out, 4800)
    assert source._inbox.qsize() == 1
    video.stop()

