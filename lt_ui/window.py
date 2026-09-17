"""The one window: photograph, floating nav, five screens underneath."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lt_core.runtime import bootstrap

from . import backdrop as backdrop_module
from . import theme
from .backdrop import Backdrop
from .engine import Engine
from .overlay import OverlayWindow
from .screens.history import HistoryScreen
from .screens.home import HomeScreen
from .screens.realtime import RealtimeScreen
from .screens.settings import SettingsScreen
from .screens.upload import UploadScreen
from .store import MODEL_ROOT, HistoryEntry, Store
from .widgets import NavBar, clear_fill


class _Scroll(QScrollArea):
    def __init__(self, child: QWidget) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 4px; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,0.22);"
            " border-radius: 4px; min-height: 32px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        viewport = self.viewport()
        viewport.setAutoFillBackground(False)
        viewport.setAttribute(Qt.WA_TranslucentBackground, True)
        clear_fill(child)
        child.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        if child.layout() is not None:
            child.layout().setSizeConstraint(QLayout.SetMinimumSize)
        self.setWidget(child)


class Window(QWidget):
    def __init__(self, store: Store | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Linguaflow")
        self.setMinimumSize(1020, 700)
        self.resize(1280, 800)
        self.store = store or Store()
        theme.set_accent(self.store.settings.accent)

        self._backdrop = Backdrop()
        backdrop_module.install(self._backdrop)

        self.engine = Engine(self)
        self.overlay = OverlayWindow(self.store)

        self._nav = NavBar(self)
        self._nav.chosen.connect(self.goto)

        self._home = HomeScreen(self)
        self._realtime = RealtimeScreen(self)
        self._upload = UploadScreen(self)
        self._history = HistoryScreen(self)
        self._settings = SettingsScreen(self)
        self._pages = {
            "home": self._home,
            "realtime": self._realtime,
            "upload": self._upload,
            "history": self._history,
            "settings": self._settings,
        }
        self._stack = QStackedWidget(self)
        self._stack.setStyleSheet("background: transparent;")
        for screen in self._pages.values():
            self._stack.addWidget(_Scroll(screen))

        nav_row = QHBoxLayout()
        nav_row.addStretch()
        nav_row.addWidget(self._nav)
        nav_row.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 28)
        layout.setSpacing(28)
        layout.addLayout(nav_row)
        layout.addWidget(self._stack, 1)

        self.goto("home")

    def closeEvent(self, event) -> None:  # noqa: N802
        self.overlay.hide()
        self.overlay.close()
        super().closeEvent(event)

    def goto(self, name: str) -> None:
        widget = self._pages.get(name)
        if widget is None:
            return
        index = list(self._pages).index(name)
        self._stack.setCurrentIndex(index)
        self._nav.set_active(name)
        widget.refresh()

    def history_changed(self) -> None:
        self._home.refresh()
        self._history.refresh()

    def settings_changed(self) -> None:
        self._realtime.refresh()
        self._settings.refresh()
        self._upload.refresh()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        if not self._backdrop.plain.isNull():
            painter.drawPixmap(0, 0, self._backdrop.plain)
        else:
            painter.fillRect(self.rect(), theme.BASE)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._backdrop.resize(self.width(), self.height())
        super().resizeEvent(event)
        self.update()


def run(
    data_dir: Path | str | None = None,
    screenshot: Path | str | None = None,
) -> int:
    bootstrap(MODEL_ROOT)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Linguaflow")
    app.setApplicationDisplayName("Linguaflow")
    if screenshot and data_dir is None:
        import tempfile
        data_dir = tempfile.mkdtemp(prefix="linguaflow-")
    store = Store(data_dir) if data_dir else Store()
    if screenshot:
        _seed_preview(store)
    window = Window(store)
    window.show()
    if screenshot:
        _capture(window, Path(screenshot))
        return 0
    return app.exec()


def _seed_preview(store: Store) -> None:
    """A couple of rows so home and history are not empty in the shots."""
    if store.entries:
        return
    store.add(HistoryEntry(
        id="preview-live", kind="live", title="Созвон с клиентом",
        source_language="ru", target_language="en",
        duration=724, created="2026-09-16T18:04:00",
    ))
    store.add(HistoryEntry(
        id="preview-file", kind="file", title="podcast_episode_42.mp3",
        source_language="en", target_language="de",
        duration=2060, created="2026-09-15T11:20:00",
    ))
    store.add(HistoryEntry(
        id="preview-talk", kind="file", title="лекция.m4a",
        source_language="en", target_language="ru",
        duration=453, created="2026-09-14T09:12:00",
    ))


def _capture(window: Window, folder: Path) -> None:
    """Grab each screen to a PNG so the handoff can be compared, not believed."""
    from PySide6.QtWidgets import QApplication

    folder.mkdir(parents=True, exist_ok=True)
    QApplication.processEvents()
    window._backdrop.resize(window.width(), window.height())
    for name in window._pages:
        window.goto(name)
        QApplication.processEvents()
        window.grab().save(str(folder / f"ui_{name}.png"), "PNG")
        if name == "settings":
            scroll = window._stack.currentWidget()
            bar = scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
            QApplication.processEvents()
            window.grab().save(str(folder / "ui_settings_rest.png"), "PNG")
            bar.setValue(0)
