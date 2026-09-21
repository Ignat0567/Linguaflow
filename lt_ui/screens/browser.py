"""A browser inside the app: watch a video, hear or read it in your language.

The page's own <video> is tapped (see lt_ui.browser), so the live session
hears the video and nothing else -- not the rest of the desktop, and not the
translation being read out over it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from lt_core.audio.capture import PageAudioSource
from lt_core.realtime.session import append_committed

from .. import glass, theme
from ..browser import HOME_URL, PageTap, address_to_url, browser_profile, plays_here
from ..i18n import _
from ..widgets import LanguagePair, clear_fill


class BrowserScreen(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        clear_fill(self)
        self._view = None
        self._page = None
        self._tap: PageTap | None = None
        self._source: PageAudioSource | None = None
        self._pending_start = False
        #: True while the engine's live session is this screen's. The
        #: realtime screen listens to the same engine signals.
        self._mine = False
        self._original = ""
        self._partial = ""
        self._translated = ""
        self._coming = ""

        # -- toolbar ------------------------------------------------------
        self._back = glass.GlassButton("←", self, size=15, height=34, padding=14)
        self._forward = glass.GlassButton("→", self, size=15, height=34, padding=14)
        self._reload = glass.GlassButton("↻", self, size=15, height=34, padding=14)
        self._address = glass.GlassInput(
            self, _("Адрес или поиск на YouTube")
        )
        self._address.returnPressed.connect(self._go)
        self._back.clicked.connect(lambda: self._page and self._view.back())
        self._forward.clicked.connect(lambda: self._page and self._view.forward())
        self._reload.clicked.connect(lambda: self._page and self._view.reload())
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(self._back)
        toolbar.addWidget(self._forward)
        toolbar.addWidget(self._reload)
        toolbar.addWidget(self._address, 1)

        # -- the page (created on first show) -----------------------------
        self._frame = glass.GlassPanel(self, radius=theme.RADIUS_PANEL)
        self._frame.setMinimumHeight(320)
        self._frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._frame_layout = QVBoxLayout(self._frame)
        self._frame_layout.setContentsMargins(6, 6, 6, 6)

        # -- captions -----------------------------------------------------
        captions = glass.GlassPanel(self, radius=theme.RADIUS_PANEL)
        captions.setFixedHeight(92)
        caption_box = QVBoxLayout(captions)
        caption_box.setContentsMargins(24, 10, 24, 10)
        caption_box.setSpacing(4)
        self._caption = glass.label(
            _("Включите перевод и запустите видео"), 17, 600, theme.PRIMARY, wrap=True
        )
        self._caption.setAlignment(Qt.AlignCenter)
        self._subcaption = glass.label("", 13, 400, 0.62, wrap=True)
        self._subcaption.setAlignment(Qt.AlignCenter)
        caption_box.addWidget(self._caption)
        caption_box.addWidget(self._subcaption)

        # -- controls -----------------------------------------------------
        self._pair = LanguagePair(self, compact=True)
        self._pair.changed.connect(self._sync_pair)
        self._translate = glass.Toggle(self)
        self._translate.toggled.connect(self._toggled)
        self._speak = glass.Toggle(self)
        self._speak.toggled.connect(self._sync_voice)
        self._overlay_btn = glass.GlassButton(_("Окно субтитров"), self, height=34)
        self._overlay_btn.clicked.connect(self._toggle_overlay)
        # The whole video, the long way: downloaded, transcribed, subtitled
        # and dubbed as a file. Also the only way for sites whose video this
        # engine cannot play.
        self._download = glass.GlassButton(_("Скачать и перевести"), self, height=34)
        self._download.clicked.connect(self._translate_as_file)
        self._status = glass.label("", 12, 400, 0.66)

        controls = QHBoxLayout()
        controls.setSpacing(14)
        controls.addWidget(self._pair)
        controls.addWidget(_pill(_("Переводить видео"), self._translate, self))
        controls.addWidget(_pill(_("Озвучивать"), self._speak, self))
        controls.addWidget(self._overlay_btn)
        controls.addWidget(self._download)
        controls.addWidget(self._status, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 0, 8, 8)
        root.setSpacing(12)
        root.addLayout(toolbar)
        root.addWidget(self._frame, 1)
        root.addWidget(captions)
        root.addLayout(controls)

        engine = app.engine
        engine.ready.connect(self._on_ready)
        engine.failed.connect(self._on_fail)
        engine.live_update.connect(self._on_update)
        engine.live_failed.connect(self._on_fail)
        engine.live_stopped.connect(self._on_stopped)
        engine.live_speaking.connect(self._on_speaking)

    # -- lifecycle ---------------------------------------------------------
    def refresh(self) -> None:
        settings = self.app.store.settings
        self._pair.set_pair(settings.from_lang, settings.to_lang)
        self._speak.blockSignals(True)
        self._speak.setChecked(settings.realtime_voice)
        self._speak.blockSignals(False)
        self._ensure_view()

    def _ensure_view(self) -> None:
        """Start the web engine the first time the screen is shown.

        It is a separate process and costs a second and a few hundred
        megabytes; nobody who never opens this screen should pay for it.
        """
        if self._view is not None:
            return
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView

        profile = browser_profile(self.app.store.root)
        self._view = QWebEngineView(self._frame)
        self._page = QWebEnginePage(profile, self._view)
        self._view.setPage(self._page)
        self._view.urlChanged.connect(self._show_url)
        self._frame_layout.addWidget(self._view)
        self._tap = PageTap(self._page, self)
        self._tap.state.connect(self._on_tap_state)
        last = self.app.store.settings.browser_url
        self._view.load(QUrl(last if last.startswith("http") else HOME_URL))

    def shutdown(self) -> None:
        """Stop translating before the widgets go (language change, quit)."""
        if self._mine or self._pending_start:
            self._pending_start = False
            self.app.engine.stop_live()
        if self._tap is not None:
            self._tap.stop()

    def open_url(self, url: QUrl) -> None:
        self._ensure_view()
        self._view.load(url)

    # -- navigation --------------------------------------------------------
    def _go(self) -> None:
        url = address_to_url(self._address.text())
        if url is not None:
            self.open_url(url)
            self._view.setFocus()

    def _show_url(self, url: QUrl) -> None:
        if not self._address.hasFocus():
            self._address.setText(url.toString())
        if url.scheme() in ("http", "https"):
            self.app.store.settings.browser_url = url.toString()
            self.app.store.save_settings()
        if not plays_here(url) and not self._mine:
            self._status.setText(_("Видео с этого сайта здесь не воспроизводится — нажмите «Скачать и перевести»"))

    def _translate_as_file(self) -> None:
        if self._view is None:
            return
        url = self._view.url().toString()
        if url.startswith("http"):
            self.app.translate_link(url)

    # -- settings ----------------------------------------------------------
    def _sync_pair(self) -> None:
        source, target = self._pair.pair()
        self.app.store.settings.from_lang = source
        self.app.store.settings.to_lang = target
        self.app.store.save_settings()

    def _sync_voice(self, on: bool) -> None:
        self.app.store.settings.realtime_voice = on
        self.app.store.save_settings()

    # -- translation -------------------------------------------------------
    def _toggled(self, on: bool) -> None:
        if on:
            if self.app.engine.live_running and not self._mine:
                self._refuse(_("Сейчас идёт живой перевод на экране «Реальное время»."))
                return
            self._ensure_view()
            self._pending_start = True
            self._original = self._partial = self._translated = self._coming = ""
            self._status.setText(_("Загружаю модели…"))
            self.app.engine.prepare(self.app.store.settings)
        else:
            self._pending_start = False
            if self._mine:
                self.app.engine.stop_live()
                self._status.setText(_("Останавливаю…"))

    def _on_ready(self) -> None:
        if not self._pending_start:
            return
        self._pending_start = False
        self._source = PageAudioSource()
        self._mine = True
        self._tap.start(self._source)
        self._status.setText(_("Жду, когда заиграет видео"))
        if self.app.store.settings.overlay:
            self.app.overlay.reveal()
            self.app.overlay.set_caption(listening=True)
        self.app.engine.start_live(self.app.store.settings, source=self._source)

    def _on_speaking(self, speaking: bool) -> None:
        if self._mine and self._tap is not None:
            self._tap.duck(speaking)

    def _on_tap_state(self, state: str) -> None:
        if not self._mine:
            return
        self._status.setText({
            "listening": _("Слушаю видео"),
            "ad": _("Идёт реклама — её не перевожу"),
            "waiting": (
                _("Жду, когда заиграет видео")
                if self._view is None or plays_here(self._view.url())
                else _("Видео с этого сайта здесь не воспроизводится — нажмите «Скачать и перевести»")
            ),
        }.get(state, ""))

    def _on_update(self, update) -> None:
        if not self._mine:
            return
        if update.committed:
            self._original = append_committed(self._original, update)
            self._partial = ""
        if update.partial:
            self._partial = update.partial
        self._coming = update.partial_translation
        if update.translation:
            self._translated = update.translation
            self._coming = ""
            self._original = ""
        self._render()

    def _render(self) -> None:
        # The settled sentence, and the next one as it forms, in a lighter
        # hand; the original underneath, trimmed to its latest words.
        shown = self._translated
        if self._coming:
            shown = f"{shown} {self._coming}".strip() if shown else self._coming
        self._caption.setText(_tail(shown, 150) or "…")
        original = f"{self._original} {self._partial}".strip()
        self._subcaption.setText(_tail(original, 140))
        overlay = getattr(self.app, "overlay", None)
        if overlay is not None and overlay.isVisible():
            overlay.set_caption(
                original=original,
                translated=shown,
                speaker=None,
                listening=True,
            )

    def _on_stopped(self) -> None:
        if not self._mine:
            return
        self._finish(_("Остановлено"))

    def _on_fail(self, message: str) -> None:
        if not (self._mine or self._pending_start):
            return
        self._pending_start = False
        self._finish(message)

    def _finish(self, message: str) -> None:
        self._mine = False
        if self._tap is not None:
            self._tap.stop()
        self._source = None
        self._status.setText(message)
        self._translate.blockSignals(True)
        self._translate.setChecked(False)
        self._translate.blockSignals(False)

    def _refuse(self, message: str) -> None:
        self._status.setText(message)
        self._translate.blockSignals(True)
        self._translate.setChecked(False)
        self._translate.blockSignals(False)

    def _toggle_overlay(self) -> None:
        overlay = self.app.overlay
        visible = not overlay.isVisible()
        self.app.store.settings.overlay = visible
        self.app.store.save_settings()
        if visible:
            overlay.reveal()
            self._render()
        else:
            overlay.hide()


def _pill(caption: str, toggle, parent: QWidget) -> QWidget:
    pill = glass.GlassPanel(parent, radius=theme.RADIUS_PILL)
    pill.setFixedHeight(42)
    row = QHBoxLayout(pill)
    row.setContentsMargins(16, 4, 10, 4)
    row.setSpacing(12)
    row.addWidget(glass.label(caption, 13, 500, 0.82))
    row.addWidget(toggle)
    return pill


def _tail(text: str, limit: int) -> str:
    """The end of a long line, cut at a word, for a strip that shows one."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    space = cut.find(" ")
    return "…" + (cut[space + 1:] if 0 <= space < 30 else cut)
