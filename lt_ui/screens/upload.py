"""File mode: drop a recording, watch it become subtitles."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lt_core.subtitles.export import format_srt_time

from .. import glass, theme
from ..i18n import _
from ..store import (
    ROOT,
    HistoryEntry,
    display_name,
    format_clock,
    new_id,
)
from ..widgets import LanguagePair, clear_fill, dashed_panel


def _filter() -> str:
    """Built when the dialog opens, not at import: the language can change."""
    return (
        f'{_("Медиа")} (*.mp3 *.wav *.m4a *.aac *.flac *.ogg '
        f'*.mp4 *.mov *.mkv *.webm);;{_("Все файлы")} (*.*)'
    )
_EXAMPLE = ROOT / "spike" / "audio" / "lecture.m4a"


class UploadScreen(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        clear_fill(self)
        self._path: Path | None = None
        self._pending = False
        self._result = None
        self._job_id = ""

        self._stack = QStackedWidget(self)
        self._stack.setStyleSheet("background: transparent;")
        self._idle = _Idle(self)
        self._ready = _Ready(self)
        self._busy = _Busy(self)
        self._done = _Done(self)
        for page in (self._idle, self._ready, self._busy, self._done):
            self._stack.addWidget(page)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(self._stack)

        engine = app.engine
        engine.status.connect(self._busy.set_stage)
        engine.ready.connect(self._on_ready)
        engine.failed.connect(self._on_fail)
        engine.batch_stage.connect(self._busy.set_stage)
        engine.batch_progress.connect(self._busy.set_progress)
        engine.batch_done.connect(self._on_done)
        engine.batch_failed.connect(self._on_fail)

    def refresh(self) -> None:
        self._idle.sync()
        self._ready.sync()

    def _sync_pair(self) -> None:
        # Two pages carry a language pair, and the one that changed is the one
        # to read. Reading `_idle` from both meant a change made on the
        # confirmation screen was thrown away without a sign.
        page = self._stack.currentWidget()
        pair = getattr(page, "pair", None) or self._idle.pair
        source, target = pair.pair()
        settings = self.app.store.settings
        settings.detect_language = source == "auto"
        if source != "auto":
            settings.from_lang = source
        settings.to_lang = target
        self.app.store.save_settings()

    def open_path(self, path: str | Path) -> None:
        target = Path(path)
        if not target.exists():
            self._busy.set_stage(_("Файл не найден: {name}", name=target.name))
            self._stack.setCurrentWidget(self._busy)
            return
        # Chosen, not started. `start` is what begins the work.
        self._path = target
        self._ready.show_file(target)
        self._stack.setCurrentWidget(self._ready)

    def start(self) -> None:
        """Begin the run the user has now asked for."""
        if self._path is None:
            return
        self._pending = True
        self._job_id = new_id()
        self._busy.reset(self._path.name)
        self._stack.setCurrentWidget(self._busy)
        self.app.engine.prepare(self.app.store.settings)

    def reset(self) -> None:
        self._path = None
        self._pending = False
        self._result = None
        self._stack.setCurrentWidget(self._idle)

    def _on_ready(self) -> None:
        if not self._pending or self._path is None:
            return
        self._pending = False
        output = self.app.store.job_dir(self._job_id)
        self.app.engine.start_batch(self._path, self.app.store.settings, output)

    def _on_fail(self, message: str) -> None:
        self._pending = False
        self._busy.set_stage(message)
        self._busy.set_progress(0.0)

    def _on_done(self, result) -> None:
        self._result = result
        settings = self.app.store.settings
        folder = self.app.store.job_dir(self._job_id)
        outputs = {name: str(path) for name, path in result.outputs.items()}
        self.app.store.add(HistoryEntry(
            id=self._job_id,
            kind="file",
            title=result.media.title or (self._path.name if self._path else _("файл")),
            source_language=result.transcript.language,
            target_language=result.target_language or settings.to_lang,
            duration=result.media.duration,
            created=datetime.now().isoformat(timespec="seconds"),
            folder=str(folder),
            outputs=outputs,
        ))
        self.app.history_changed()
        self._done.show_result(result, settings)
        self._stack.setCurrentWidget(self._done)
        if settings.notify:
            self.window().activateWindow()


class _Idle(QWidget):
    def __init__(self, screen: UploadScreen) -> None:
        super().__init__()
        self.screen = screen
        clear_fill(self)
        self.pair = LanguagePair(self, allow_auto=True)
        self.pair.changed.connect(screen._sync_pair)

        from_label = glass.eyebrow(_("Исходный язык"))
        to_label = glass.eyebrow(_("Перевод на"))
        captions = QHBoxLayout()
        captions.setContentsMargins(4, 0, 4, 0)
        captions.addWidget(from_label)
        captions.addStretch()
        captions.addWidget(to_label)

        zone = _Dropzone(screen)
        demo = glass.GlassButton(_("Выбрать файл"), zone, primary=True)
        demo.clicked.connect(zone.pick)
        example = glass.TextLink(_("Открыть пример"), zone, size=13)
        example.clicked.connect(lambda: screen.open_path(_EXAMPLE) if _EXAMPLE.exists() else None)
        if not _EXAMPLE.exists():
            example.hide()

        inner = QVBoxLayout(zone)
        inner.setContentsMargins(40, 48, 40, 40)
        inner.setSpacing(0)
        inner.setAlignment(Qt.AlignCenter)
        title = glass.label(_("Перетащите файл"), 36, 700, tracking=-2)
        title.setAlignment(Qt.AlignCenter)
        hint = glass.label(
            _("видео, аудио или песня — MP3, WAV, MP4, MOV"),
            13, 400, theme.TERTIARY,
        )
        hint.setAlignment(Qt.AlignCenter)
        inner.addWidget(title)
        inner.addSpacing(10)
        inner.addWidget(hint)
        inner.addSpacing(28)
        inner.addWidget(demo, 0, Qt.AlignHCenter)
        inner.addSpacing(14)
        inner.addWidget(example, 0, Qt.AlignHCenter)

        column = QVBoxLayout(self)
        column.setAlignment(Qt.AlignCenter)
        column.setSpacing(0)
        pair_wrap = QWidget()
        clear_fill(pair_wrap)
        pair_wrap.setFixedWidth(560)
        pair_layout = QVBoxLayout(pair_wrap)
        pair_layout.setContentsMargins(0, 0, 0, 0)
        pair_layout.setSpacing(8)
        pair_layout.addLayout(captions)
        pair_layout.addWidget(self.pair)
        column.addWidget(pair_wrap)
        column.addSpacing(18)
        zone.setFixedWidth(560)
        zone.setMinimumHeight(280)
        zone.setMaximumHeight(380)
        column.addWidget(zone)

    def sync(self) -> None:
        settings = self.screen.app.store.settings
        source = "auto" if settings.detect_language else settings.from_lang
        self.pair.set_pair(source, settings.to_lang)


class _Dropzone(glass.GlassPanel):
    def __init__(self, screen: UploadScreen) -> None:
        super().__init__(radius=28)
        self.screen = screen
        self.setAcceptDrops(True)
        self.setCursor(self.cursor())
        self.setMinimumHeight(280)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        dashed_panel(self, painter, 28)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.pick()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls:
            self.screen.open_path(urls[0].toLocalFile())

    def pick(self) -> None:
        # Not `path, _ = ...`. `_` is the translator in this module, and
        # unpacking into it shadows the import for the whole function -- the
        # very next argument is a `_()` call, so the dialog raised
        # UnboundLocalError before it ever opened.
        path, _chosen_filter = QFileDialog.getOpenFileName(
            self, _("Выберите медиафайл"), str(ROOT), _filter()
        )
        if path:
            self.screen.open_path(path)


class _Ready(QWidget):
    """The file is chosen; nothing has started yet.

    Starting the moment a file is dropped takes the decision away from the
    person who dropped it -- and the run is minutes long, loads models and
    may send lines to a service. The pair and the settings can still be
    changed on this screen, which is the point of stopping here.
    """

    def __init__(self, screen: UploadScreen) -> None:
        super().__init__()
        self.screen = screen
        clear_fill(self)

        self.pair = LanguagePair(self, allow_auto=True)
        self.pair.changed.connect(screen._sync_pair)
        captions = QHBoxLayout()
        captions.setContentsMargins(4, 0, 4, 0)
        captions.addWidget(glass.eyebrow(_("Исходный язык")))
        captions.addStretch()
        captions.addWidget(glass.eyebrow(_("Перевод на")))

        panel = glass.GlassPanel(self, radius=theme.RADIUS_PANEL)
        panel.setFixedWidth(560)
        inner = QVBoxLayout(panel)
        inner.setContentsMargins(36, 32, 36, 32)
        inner.setSpacing(0)
        inner.setAlignment(Qt.AlignCenter)

        self._name = glass.label("", 22, 700, tracking=-1, wrap=True)
        self._name.setAlignment(Qt.AlignCenter)
        self._meta = glass.label("", 13, 400, theme.TERTIARY)
        self._meta.setAlignment(Qt.AlignCenter)
        start = glass.GlassButton(_("Начать перевод"), panel, primary=True,
                                  height=42, size=14)
        start.clicked.connect(screen.start)
        another = glass.TextLink(_("Другой файл"), panel, size=13)
        another.clicked.connect(screen.reset)

        inner.addWidget(self._name)
        inner.addSpacing(8)
        inner.addWidget(self._meta)
        inner.addSpacing(26)
        inner.addWidget(start, 0, Qt.AlignHCenter)
        inner.addSpacing(14)
        inner.addWidget(another, 0, Qt.AlignHCenter)

        column = QVBoxLayout(self)
        column.setAlignment(Qt.AlignCenter)
        column.setSpacing(0)
        pair_wrap = QWidget()
        clear_fill(pair_wrap)
        pair_wrap.setFixedWidth(560)
        pair_layout = QVBoxLayout(pair_wrap)
        pair_layout.setContentsMargins(0, 0, 0, 0)
        pair_layout.setSpacing(8)
        pair_layout.addLayout(captions)
        pair_layout.addWidget(self.pair)
        column.addWidget(pair_wrap)
        column.addSpacing(18)
        column.addWidget(panel, 0, Qt.AlignHCenter)

    def show_file(self, path: Path) -> None:
        self._name.setText(path.name)
        self._meta.setText(self._describe(path))
        self.sync()

    @staticmethod
    def _describe(path: Path) -> str:
        """Length where it can be read cheaply, size where it cannot.

        A link has nothing to read until it has been fetched, and fetching it
        to fill in a caption before the user has pressed anything would be
        exactly the eagerness this screen exists to stop.
        """
        try:
            from lt_core.media import probe

            info = probe(path)
            if info.duration:
                return format_clock(info.duration)
        except Exception:  # noqa: BLE001 -- a caption is not worth an error
            pass
        try:
            return f"{path.stat().st_size / (1024 * 1024):.1f} МБ"
        except OSError:
            return ""

    def sync(self) -> None:
        settings = self.screen.app.store.settings
        source = "auto" if settings.detect_language else settings.from_lang
        self.pair.set_pair(source, settings.to_lang)


class _Busy(QWidget):
    def __init__(self, screen: UploadScreen) -> None:
        super().__init__()
        clear_fill(self)
        self._ring = glass.ProgressRing(self, 160)
        self._stage = glass.label(_("Загружаю модели…"), 13, 400, 0.75)
        self._stage.setAlignment(Qt.AlignCenter)
        self._name = glass.label("", 12, 400, theme.MUTED)
        self._name.setAlignment(Qt.AlignCenter)
        column = QVBoxLayout(self)
        column.setAlignment(Qt.AlignCenter)
        column.setSpacing(18)
        column.addStretch()
        column.addWidget(self._ring, 0, Qt.AlignHCenter)
        column.addWidget(self._stage)
        column.addWidget(self._name)
        column.addStretch()

    def reset(self, name: str) -> None:
        self._ring.set_value(0.0)
        self._stage.setText(_("Загружаю модели…"))
        self._name.setText(name)

    def set_stage(self, text: str) -> None:
        self._stage.setText(text)

    def set_progress(self, fraction: float) -> None:
        self._ring.set_value(fraction)


class _Done(QWidget):
    def __init__(self, screen: UploadScreen) -> None:
        super().__init__()
        self.screen = screen
        clear_fill(self)
        self._panel = glass.GlassPanel(self, radius=26)
        self._panel.setMaximumWidth(760)
        self._body = QVBoxLayout(self._panel)
        self._body.setContentsMargins(36, 32, 36, 28)
        self._body.setSpacing(0)
        row = QHBoxLayout(self)
        row.addStretch()
        row.addWidget(self._panel, 1)
        row.addStretch()

    def show_result(self, result, settings) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(6)
        name = glass.label(result.media.title, 26, 700, tracking=-2, wrap=True)
        source = display_name(result.transcript.language)
        if settings.detect_language:
            source = f'{source} · {_("авто")}'
        meta = glass.label(
            f"{format_clock(result.media.duration)}  ·  "
            f"{source} → {display_name(settings.to_lang)}",
            12, 400, theme.TERTIARY,
        )
        titles.addWidget(name)
        titles.addWidget(meta)
        reset = glass.TextLink(_("Другой файл"), self, size=13)
        reset.clicked.connect(self.screen.reset)
        header.addLayout(titles, 1)
        header.addWidget(reset, 0, Qt.AlignTop)
        self._body.addLayout(header)
        self._body.addSpacing(20)

        cues = result.cues
        translated = result.translated_cues or ()
        for index, cue in enumerate(cues[:24]):
            other = translated[index].flat_text if index < len(translated) else ""
            self._body.addWidget(_CueRow(cue.start, cue.flat_text, other))
            self._body.addSpacing(16)
        if len(cues) > 24:
            more = glass.label(
                _("… и ещё {count} субтитров в сохранённых файлах",
                  count=len(cues) - 24),
                12, 400, theme.MUTED,
            )
            self._body.addWidget(more)
            self._body.addSpacing(10)

        chips = QHBoxLayout()
        chips.setSpacing(10)
        labels = {
            "srt": _("Субтитры (.srt)"),
            "srt." + settings.to_lang: f_("Перевод (.srt)"),
            "srt.bilingual": _("Оба языка (.srt)"),
            "vtt": _("Субтитры (.vtt)"),
            "txt": _("Текст (.txt)"),
            "audio": _("Озвучка (.wav)"),
            "video": _("Видео с переводом"),
        }
        for key, path in result.outputs.items():
            caption = labels.get(key)
            if caption is None and key.startswith("srt."):
                caption = f'{_(_("Перевод (.srt)"))} · {key}'
            if caption is None:
                continue
            button = glass.GlassButton(caption, self, height=36, padding=16)
            button.clicked.connect(
                lambda _=False, p=str(path): QDesktopServices.openUrl(
                    QUrl.fromLocalFile(p)
                )
            )
            chips.addWidget(button)
        chips.addStretch()
        self._body.addSpacing(12)
        self._body.addLayout(chips)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                _Done._clear_layout(item.layout())


class _CueRow(QWidget):
    def __init__(self, start: float, original: str, translated: str) -> None:
        super().__init__()
        clear_fill(self)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)
        stamp = glass.label(format_srt_time(start)[3:-4], 11, 600, theme.MUTED)
        stamp.setFixedWidth(52)
        stamp.setAlignment(Qt.AlignRight | Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        texts.addWidget(glass.label(original, 17, 500, wrap=True))
        if translated:
            texts.addWidget(glass.label(translated, 14, 400, 0.68, wrap=True))
        row.addWidget(stamp, 0, Qt.AlignTop)
        row.addLayout(texts, 1)
