"""Past jobs, as a list of glass rows."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from .. import glass, theme
from ..i18n import _
from ..store import format_clock, format_date
from ..widgets import clear_fill


class HistoryScreen(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        clear_fill(self)
        title = glass.label(_("История переводов"), 36, 700, tracking=-2)
        title.setAlignment(Qt.AlignCenter)
        self._list = QVBoxLayout()
        self._list.setSpacing(12)
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 0, 8, 8)
        column.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self._clear = glass.TextLink(_("Очистить историю"), self, size=13)
        self._clear.clicked.connect(self._on_clear)
        self._confirming = False
        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 8)
        header.addStretch()
        header.addWidget(self._clear)

        wrap = QWidget()
        clear_fill(wrap)
        wrap.setFixedWidth(700)
        stacked = QVBoxLayout(wrap)
        stacked.setContentsMargins(0, 0, 0, 0)
        stacked.setSpacing(8)
        stacked.addLayout(header)
        stacked.addLayout(self._list)
        self._header = wrap

        column.addWidget(title)
        column.addSpacing(20)
        column.addWidget(wrap, 0, Qt.AlignHCenter)
        column.addStretch()

    def refresh(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        entries = self.app.store.entries
        self._reset_clear()
        self._clear.setVisible(bool(entries))
        if not entries:
            empty = glass.label(_("Пока нет переводов."), 14, 400, theme.MUTED)
            empty.setAlignment(Qt.AlignCenter)
            self._list.addWidget(empty)
            return
        for entry in entries:
            self._list.addWidget(_Row(entry))


    # -- clearing the list -----------------------------------------------
    def _reset_clear(self) -> None:
        self._confirming = False
        self._clear.setText(_("Очистить историю"))

    def _on_clear(self) -> None:
        """Asks once, in place, rather than opening a dialog.

        A confirmation box in this window would be the one unstyled thing in
        it, and the action is small: the list goes, the files stay.
        """
        if not self._confirming:
            self._confirming = True
            self._clear.setText(_("Очистить? Файлы останутся — нажмите ещё раз"))
            return
        self.app.store.clear_history()
        self._reset_clear()
        self.app.history_changed()

    def hideEvent(self, event) -> None:  # noqa: N802
        # Leaving the screen half-way through a confirmation and coming back
        # to a primed button would be a trap.
        self._reset_clear()
        super().hideEvent(event)


class _Row(glass.GlassPanel):
    def __init__(self, entry) -> None:
        super().__init__(radius=theme.RADIUS_ROW)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(16)
        row.addWidget(_Dot(entry.is_live), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        title = glass.label(entry.title, 18, 600)
        meta = glass.label(
            f"{entry.source_language.upper()} → {entry.target_language.upper()}"
            f"    {format_clock(entry.duration)}"
            f"    {format_date(entry.created)}",
            12, 400, theme.TERTIARY,
        )
        texts.addWidget(title)
        texts.addWidget(meta)
        row.addLayout(texts, 1)
        if entry.folder and Path(entry.folder).exists():
            # It opens the folder; it never downloaded anything. A label that
            # describes a different action is worse than no label.
            link = glass.TextLink(_("Открыть папку"), self, size=12)
            link.clicked.connect(
                lambda: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(entry.folder)
                )
            )
            row.addWidget(link, 0, Qt.AlignVCenter)


class _Dot(QWidget):
    def __init__(self, live: bool) -> None:
        super().__init__()
        self._live = live
        self.setFixedSize(10, 10)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.accent(1.0) if self._live else theme.ink(0.60))
        painter.drawEllipse(self.rect())
