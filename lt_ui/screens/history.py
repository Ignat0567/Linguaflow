"""Past jobs, as a list of glass rows."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from .. import glass, theme
from ..store import format_clock, format_date
from ..widgets import clear_fill


class HistoryScreen(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        clear_fill(self)
        title = glass.label("История переводов", 36, 700, tracking=-2)
        title.setAlignment(Qt.AlignCenter)
        self._list = QVBoxLayout()
        self._list.setSpacing(12)
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 0, 8, 8)
        column.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        column.addWidget(title)
        column.addSpacing(28)
        wrap = QWidget()
        clear_fill(wrap)
        wrap.setMaximumWidth(700)
        wrap.setLayout(self._list)
        column.addWidget(wrap)
        column.addStretch()

    def refresh(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        entries = self.app.store.entries
        if not entries:
            empty = glass.label("Пока нет переводов.", 14, 400, theme.MUTED)
            empty.setAlignment(Qt.AlignCenter)
            self._list.addWidget(empty)
            return
        for entry in entries:
            self._list.addWidget(_Row(entry))


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
            link = glass.TextLink("Скачать  ↓", self, size=12)
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
        painter.setBrush(theme.accent(1.0) if self._live else theme.white(0.60))
        painter.drawEllipse(self.rect())
