"""A downloaded video, played inside the browser screen.

For the sites whose video the web engine cannot play (X: H.264 only, and the
engine has no H.264). yt-dlp fetches the post's video, Qt shows the picture
-- QtMultimedia decodes H.264 -- and the sound is played by FilePlayback,
which is also the clock the picture follows. See lt_core.audio.playback for
why the sound does not go through Qt.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from lt_core.audio.playback import FilePlayback
from lt_core.media import MediaError, decode_audio, fetch_url

from . import glass
from .i18n import _
from .store import format_clock
from .widgets import clear_fill

#: How far the picture may wander from the sound before it is put back.
#: Below this a correction is a visible jump for an invisible error.
DRIFT = 0.25


class DownloadWorker(QThread):
    """yt-dlp and the soundtrack's decoding, off the GUI thread."""

    done = Signal(object, object)  # MediaInfo, int16 frames
    failed = Signal(str)

    RATE = 48_000

    def __init__(self, url: str, folder: Path, cookies: Path | None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.url = url
        self.folder = folder
        self.cookies = cookies

    def run(self) -> None:
        try:
            info = fetch_url(self.url, self.folder, want_video=True, cookies=self.cookies)
            frames = decode_audio(info.path, rate=self.RATE, channels=2)
        except MediaError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:  # noqa: BLE001 -- surface anything
            self.failed.emit(str(error))
            return
        finally:
            # The session in it has done its job; it does not stay on disk.
            if self.cookies is not None:
                Path(self.cookies).unlink(missing_ok=True)
        self.done.emit(info, frames)


class DownloadedVideo(QWidget):
    """Picture from Qt, sound from FilePlayback, the one following the other."""

    closed = Signal()
    ended = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        clear_fill(self)
        from PySide6.QtMultimedia import QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget

        self._picture = QMediaPlayer(self)
        self._screen = QVideoWidget(self)
        self._picture.setVideoOutput(self._screen)
        self.sound: FilePlayback | None = None

        self._back = glass.GlassButton(_("← К странице"), self, height=32, padding=16)
        self._back.clicked.connect(self._close)
        self._toggle = glass.GlassButton("❚❚", self, height=32, padding=16)
        self._toggle.clicked.connect(self.toggle)
        self._clock = glass.label("", 12, 400, 0.7)
        self._title = glass.label("", 13, 600, 0.9)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        bar.addWidget(self._back)
        bar.addWidget(self._toggle)
        bar.addWidget(self._clock)
        bar.addWidget(self._title, 1)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(self._screen, 1)
        column.addLayout(bar)

        self._sync = QTimer(self)
        self._sync.setInterval(250)
        self._sync.timeout.connect(self._follow)
        self._restore = QTimer(self)
        self._restore.setSingleShot(True)
        self._restore.timeout.connect(lambda: self._set_volume(1.0))

    # -- loading -----------------------------------------------------------
    def load(self, path: Path, frames, rate: int, title: str, on_audio=None) -> None:
        self.stop()
        self.sound = FilePlayback(frames, rate, on_audio=on_audio)
        self._picture.setSource(QUrl.fromLocalFile(str(path)))
        self._title.setText(title)
        self._show_clock()

    # -- transport ---------------------------------------------------------
    def play(self) -> None:
        if self.sound is None:
            return
        self._picture.setPosition(int(self.sound.position * 1000))
        self.sound.play()
        self._picture.play()
        self._toggle.setText("❚❚")
        self._sync.start()

    def pause(self) -> None:
        if self.sound is not None:
            self.sound.pause()
        self._picture.pause()
        self._toggle.setText("▶")
        self._sync.stop()

    def toggle(self) -> None:
        if self.sound is not None and self.sound.playing:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._sync.stop()
        self._restore.stop()
        self._picture.stop()
        if self.sound is not None:
            self.sound.close()
            self.sound = None

    def _close(self) -> None:
        self.stop()
        self.closed.emit()

    # -- keeping the picture with the sound --------------------------------
    def _follow(self) -> None:
        sound = self.sound
        if sound is None:
            return
        if sound.finished.is_set():
            self.pause()
            self.ended.emit()
            return
        drift = self._picture.position() / 1000 - sound.position
        if abs(drift) > DRIFT:
            self._picture.setPosition(int(sound.position * 1000))
        self._show_clock()

    def _show_clock(self) -> None:
        if self.sound is None:
            self._clock.setText("")
            return
        self._clock.setText(
            f"{format_clock(self.sound.position)} / {format_clock(self.sound.duration)}"
        )

    # -- under a translation being read out ---------------------------------
    def duck(self, speaking: bool) -> None:
        """The same contract as the page tap's: down for a line, up after."""
        from lt_core.tts.dub import DUCK_BRIDGE, DUCK_GAIN

        if speaking:
            self._restore.stop()
            self._set_volume(DUCK_GAIN)
        elif self.sound is not None and self.sound.volume < 1.0:
            self._restore.start(int(DUCK_BRIDGE * 1000))

    def _set_volume(self, level: float) -> None:
        if self.sound is not None:
            self.sound.set_volume(level)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space:
            self.toggle()
            return
        super().keyPressEvent(event)
