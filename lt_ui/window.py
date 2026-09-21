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
from . import system_backdrop
from lt_core import messages

from . import i18n
from . import theme
from .backdrop import Backdrop
from .engine import Engine
from .overlay import OverlayWindow
from .screens.browser import BrowserScreen
from .screens.history import HistoryScreen
from .screens.home import HomeScreen
from .screens.realtime import RealtimeScreen
from .screens.settings import SettingsScreen
from .screens.upload import UploadScreen
from .store import MODEL_ROOT, HistoryEntry, Store
from .widgets import NavBar, Wordmark, clear_fill


class _Scroll(QScrollArea):
    def __init__(self, child: QWidget) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        viewport = self.viewport()
        viewport.setAutoFillBackground(False)
        viewport.setAttribute(Qt.WA_TranslucentBackground, True)
        clear_fill(child)
        child.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        if child.layout() is not None:
            child.layout().setSizeConstraint(QLayout.SetMinimumSize)
        self.setWidget(child)
        self.apply_sheet()

    def apply_sheet(self) -> None:
        handle = (
            "rgba(13,15,26,0.22)" if theme.is_light() else "rgba(255,255,255,0.22)"
        )
        self.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 4px; }"
            f"QScrollBar::handle:vertical {{ background: {handle};"
            " border-radius: 4px; min-height: 32px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )


class Window(QWidget):
    def __init__(self, store: Store | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Linguaflow")
        # The window lets the desktop through, and the compositor is asked to
        # frost it on the way, so that what shows through is a surface rather
        # than somebody's browser. Two things are needed and only together:
        # a window surface that really carries alpha, and the backdrop drawn
        # into it at less than full strength. `setWindowOpacity` looks like
        # the shorter road and is not -- it makes the whole window a layered
        # one blended against the literal desktop, so the frosted sheet is
        # composed behind an opaque surface and never seen. Measured: at 0.5
        # opacity with the backdrop asked for and granted, a page of text
        # behind the window was readable through it, word for word.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.blurred_behind = system_backdrop.blur_behind(self)
        self.setMinimumSize(1020, 700)
        self.resize(1280, 800)
        self.store = store or Store()
        theme.set_accent(self.store.settings.accent)
        theme.set_mode(self.store.settings.appearance)
        i18n.set_language(self.store.settings.ui_language)
        # The core speaks its own Russian unless something tells it otherwise.
        # This is that something; see lt_core.messages for why it is a seam.
        messages.install(i18n.t)

        self._backdrop = Backdrop()
        backdrop_module.install(self._backdrop)

        self.engine = Engine(self, keys=self.store.keys, data_root=self.store.root)
        self.overlay = OverlayWindow(self.store)

        self._frame = QVBoxLayout(self)
        # Left and top are the same: the name sits the same distance from
        # each edge, which is what «with an inset from both» means.
        self._frame.setContentsMargins(24, 24, 24, 28)
        self._frame.setSpacing(0)
        self._shell: QWidget | None = None
        self._build_shell()
        self.goto("home")

    def _build_shell(self) -> None:
        """Build the nav and the six screens.

        Called again when the interface language changes. Every caption is
        read from the catalogue when its widget is created, so the honest way
        to change language is to build the widgets again -- cheaper to reason
        about than a setText for each of ninety strings, and it happens once,
        when a person picks a language from a list.
        """
        self._nav = NavBar(self)
        self._nav.chosen.connect(self.goto)

        self._home = HomeScreen(self)
        self._realtime = RealtimeScreen(self)
        self._browser = BrowserScreen(self)
        self._upload = UploadScreen(self)
        self._history = HistoryScreen(self)
        self._settings = SettingsScreen(self)
        self._pages = {
            "home": self._home,
            "realtime": self._realtime,
            "browser": self._browser,
            "upload": self._upload,
            "history": self._history,
            "settings": self._settings,
        }
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        for screen in self._pages.values():
            # The browser fills the height it is given; a scroll area would
            # hand it only its minimum.
            self._stack.addWidget(
                screen if screen is self._browser else _Scroll(screen)
            )

        self._mark = Wordmark(self)
        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(0, 0, 0, 0)
        nav_row.setSpacing(0)
        # The name is taller than the bar now, so they share a centre line
        # rather than a top edge.
        nav_row.addWidget(self._mark, 0, Qt.AlignLeft | Qt.AlignVCenter)
        nav_row.addStretch(1)
        nav_row.addWidget(self._nav, 0, Qt.AlignVCenter)
        nav_row.addStretch(1)
        # The nav is centred on the window, not on what is left of it, so the
        # name's width is given back on the other side.
        nav_row.addSpacing(self._mark.sizeHint().width())

        shell = QWidget(self)
        shell.setAttribute(Qt.WA_TranslucentBackground, True)
        inside = QVBoxLayout(shell)
        inside.setContentsMargins(0, 0, 0, 0)
        inside.setSpacing(28)
        inside.addLayout(nav_row)
        inside.addWidget(self._stack, 1)
        self._frame.addWidget(shell)
        self._shell = shell

    # -- appearance and language ----------------------------------------
    def apply_appearance(self) -> None:
        """Repaint everything in the mode the settings now ask for."""
        theme.set_mode(self.store.settings.appearance)
        self._backdrop.invalidate()
        self._backdrop.resize(self.width(), self.height())
        theme.restyle(self)
        for scroll in self.findChildren(_Scroll):
            scroll.apply_sheet()
        self.overlay.restyle()
        self.update()

    def apply_language(self) -> None:
        i18n.set_language(self.store.settings.ui_language)
        messages.install(i18n.t)
        current = self.current_screen
        self._browser.shutdown()
        if self._shell is not None:
            self._frame.removeWidget(self._shell)
            self._shell.setParent(None)
            self._shell.deleteLater()
            self._shell = None
        self._build_shell()
        self.overlay.restyle()
        self.goto(current)

    @property
    def current_screen(self) -> str:
        if not getattr(self, "_pages", None):
            return "home"
        index = self._stack.currentIndex()
        names = list(self._pages)
        return names[index] if 0 <= index < len(names) else "home"

    def closeEvent(self, event) -> None:  # noqa: N802
        self._browser.shutdown()
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
        # The surface has to be cleared to nothing first and then painted
        # over at less than full strength. Painting straight in `Source` mode
        # at an opacity writes an opaque surface however low the opacity is,
        # which is a window that looks right and lets nothing through --
        # measured against a sheet of strong colour behind it, and the sheet
        # did not show at all.
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setOpacity(theme.WINDOW_OPACITY)
        if not self._backdrop.plain.isNull():
            painter.drawPixmap(0, 0, self._backdrop.plain)
        else:
            painter.fillRect(self.rect(), theme.base())

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
        if name == "upload":
            busy = window._upload._busy
            busy.reset("Anthropic.mp4")
            busy.set_stage("Озвучиваю перевод")
            busy.set_progress(0.80)
            busy._ring._phase = 0.28
            window._upload._stack.setCurrentWidget(busy)
            QApplication.processEvents()
            window.grab().save(str(folder / "ui_upload_busy.png"), "PNG")
            window._upload.reset()
        if name == "settings":
            scroll = window._stack.currentWidget()
            bar = scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
            QApplication.processEvents()
            window.grab().save(str(folder / "ui_settings_rest.png"), "PNG")
            bar.setValue(0)
