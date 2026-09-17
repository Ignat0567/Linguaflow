"""Entry point: pick a mode, or jump back into a recent job."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from .. import glass, theme
from ..i18n import _
from ..store import format_clock
from ..widgets import GlassCard, clear_fill


class HomeScreen(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        clear_fill(self)

        hero = QVBoxLayout()
        hero.setAlignment(Qt.AlignCenter)
        title = glass.label(_("Что переводим сегодня?"), 52, 700, tracking=-3)
        title.setAlignment(Qt.AlignCenter)
        title.setMinimumWidth(720)
        sub = glass.label(
            _("Живой разговор или готовая запись — текст, субтитры или голос."),
            15, 400, theme.SECONDARY, wrap=True,
        )
        sub.setAlignment(Qt.AlignCenter)
        sub.setMaximumWidth(560)
        hero.addWidget(title)
        hero.addSpacing(14)
        hero.addWidget(sub)

        live = GlassCard(self, accent=True)
        live.body.addWidget(glass.eyebrow("01  ·  Live", 0.70))
        live.body.addSpacing(10)
        live.body.addWidget(glass.label(
            _("Перевод в реальном времени"), 29, 700, tracking=-2, wrap=True
        ))
        live.body.addSpacing(10)
        live.body.addWidget(glass.label(
            _("Субтитры, синхронная озвучка или разговор двух людей на разных языках."),
            13, 400, 0.80, wrap=True,
        ))
        live.body.addStretch()
        live.body.addWidget(glass.label(_("Начать  →"), 13, 600))
        live.clicked.connect(lambda: app.goto("realtime"))

        file_card = GlassCard(self)
        file_card.body.addWidget(glass.eyebrow("02  ·  File", theme.TERTIARY))
        file_card.body.addSpacing(10)
        file_card.body.addWidget(glass.label(
            _("Загрузка файла"), 29, 700, tracking=-2, wrap=True
        ))
        file_card.body.addSpacing(10)
        file_card.body.addWidget(glass.label(
            _("Видео, аудио или песня — транскрипт, субтитры и переведённая озвучка."),
            13, 400, 0.70, wrap=True,
        ))
        file_card.body.addStretch()
        file_card.body.addWidget(glass.label(_("Загрузить  →"), 13, 600))
        file_card.clicked.connect(lambda: app.goto("upload"))

        cards = QHBoxLayout()
        cards.setSpacing(20)
        cards.addWidget(live)
        cards.addWidget(file_card)

        header = QHBoxLayout()
        header.addWidget(glass.eyebrow(_("Последние переводы")))
        header.addStretch()
        more = glass.TextLink(_("Все  →"), self, size=13)
        more.clicked.connect(lambda: app.goto("history"))
        header.addWidget(more)

        self._recent = QHBoxLayout()
        self._recent.setSpacing(14)
        self._empty = glass.label(_("Пока пусто — переводы появятся здесь."), 13, 400, theme.MUTED)
        self._recent.addWidget(self._empty)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 12, 8, 8)
        root.setSpacing(0)
        root.addLayout(hero)
        root.addSpacing(36)
        root.addLayout(cards)
        root.addSpacing(52)
        root.addLayout(header)
        root.addSpacing(16)
        root.addLayout(self._recent)
        root.addStretch()

    def refresh(self) -> None:
        while self._recent.count():
            item = self._recent.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        entries = self.app.store.recent(3)
        if not entries:
            self._empty = glass.label(
                _("Пока пусто — переводы появятся здесь."), 13, 400, theme.MUTED
            )
            self._recent.addWidget(self._empty)
            return
        for entry in entries:
            self._recent.addWidget(_RecentCard(entry, self.app))
        self._recent.addStretch()


class _RecentCard(glass.GlassPanel):
    def __init__(self, entry, app) -> None:
        super().__init__(radius=theme.RADIUS_ROW)
        self.setFixedWidth(220)
        kind = _("Реальное время") if entry.is_live else _("Файл")
        tint = theme.accent(1.0) if entry.is_live else theme.ink(theme.TERTIARY)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(0)
        badge = glass.eyebrow(kind)
        badge.setStyleSheet(
            f"color: rgba({tint.red()},{tint.green()},{tint.blue()},{tint.alphaF():.2f});"
            " background: transparent;"
        )
        title = glass.label(entry.title, 14, 600)
        title.setMaximumWidth(188)
        meta = glass.label(
            f"{entry.source_language.upper()} → {entry.target_language.upper()}"
            f"    {format_clock(entry.duration)}",
            12, 400, theme.TERTIARY,
        )
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(
            f"background: rgba(255,255,255,0.20); border: none;"
            if not theme.is_light()
            else "background: rgba(13,15,26,0.16); border: none;"
        )
        layout.addWidget(badge)
        layout.addSpacing(8)
        layout.addWidget(title)
        layout.addSpacing(12)
        layout.addWidget(line)
        layout.addSpacing(10)
        layout.addWidget(meta)
        self.setCursor(self.cursor())
        glass.clickable(self, lambda: app.goto("history"))
