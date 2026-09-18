"""Composite controls built from the glass primitives.

The primitives in glass.py are the recipe. These are the pieces the screens
actually place: a language pair, a chip group, a clickable card, the nav.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lt_core import languages

from . import glass, theme
from .i18n import _
from .store import display_name


def clear_fill(widget: QWidget) -> QWidget:
    """A widget that does not paint its own rectangle over the photograph."""
    widget.setAttribute(Qt.WA_TranslucentBackground, True)
    widget.setAutoFillBackground(False)
    widget.setStyleSheet("background: transparent;")
    return widget


class ChipGroup(QWidget):
    """Exclusive chips. One of them is always on."""

    changed = Signal(str)

    def __init__(
        self,
        items: Iterable[tuple[str, str]],
        parent: QWidget | None = None,
        height: int = 34,
        stretch: bool = True,
    ) -> None:
        super().__init__(parent)
        clear_fill(self)
        self._keys: list[str] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for index, (key, text) in enumerate(items):
            chip = glass.Chip(text, self, height=height)
            chip.setCheckable(True)
            self._group.addButton(chip, index)
            self._keys.append(key)
            row.addWidget(chip)
        if stretch:
            row.addStretch()
        self._group.idClicked.connect(self._emit)

    def _emit(self, index: int) -> None:
        if 0 <= index < len(self._keys):
            self.changed.emit(self._keys[index])

    def set_value(self, key: str) -> None:
        if key in self._keys:
            button = self._group.button(self._keys.index(key))
            if button is not None:
                button.setChecked(True)

    def value(self) -> str:
        checked = self._group.checkedId()
        if 0 <= checked < len(self._keys):
            return self._keys[checked]
        return self._keys[0] if self._keys else ""


class LanguagePair(QWidget):
    """From / to pickers that refuse to name the same language twice.

    Translating a language into itself is a hard error downstream. Catching
    it here, by swapping the other side, means the rest of the program never
    has to explain that error to someone who just clicked a dropdown.
    """

    changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        compact: bool = False,
        allow_auto: bool = False,
    ) -> None:
        super().__init__(parent)
        clear_fill(self)
        self._allow_auto = allow_auto
        from_width = 188 if allow_auto else (136 if compact else 160)
        self._from = glass.GlassSelect(self, width=from_width)
        self._to = glass.GlassSelect(self, width=136 if compact else 160)
        self._fill()
        self._from.currentIndexChanged.connect(self._from_changed)
        self._to.currentIndexChanged.connect(self._to_changed)

        swap = glass.TextLink("⇄", self, size=16, alpha=0.7)
        swap.clicked.connect(self._swap)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(self._from)
        row.addWidget(swap)
        row.addWidget(self._to)

    def _fill(self) -> None:
        self._from.blockSignals(True)
        self._to.blockSignals(True)
        self._from.clear()
        self._to.clear()
        if self._allow_auto:
            self._from.addItem(_("Автоопределение"), "auto")
        for code, language in languages.active().items():
            label = display_name(language.code)
            self._from.addItem(label, code)
            self._to.addItem(label, code)
        self._from.blockSignals(False)
        self._to.blockSignals(False)

    def set_pair(self, source: str, target: str) -> None:
        self._from.blockSignals(True)
        self._to.blockSignals(True)
        self._from.setCurrentIndex(max(0, self._from.findData(source)))
        self._to.setCurrentIndex(max(0, self._to.findData(target)))
        self._from.blockSignals(False)
        self._to.blockSignals(False)

    def pair(self) -> tuple[str, str]:
        return self._from.currentData() or "ru", self._to.currentData() or "en"

    def _from_changed(self) -> None:
        source, target = self.pair()
        if source != "auto" and source == target:
            # Pick the first other language so the dropdown never lands on a
            # pair the translator will refuse.
            other = next(
                (code for code in languages.ACTIVE if code != source), source
            )
            self._to.blockSignals(True)
            self._to.setCurrentIndex(max(0, self._to.findData(other)))
            self._to.blockSignals(False)
        self.changed.emit()

    def _to_changed(self) -> None:
        source, target = self.pair()
        if source != "auto" and source == target:
            other = next(
                (code for code in languages.ACTIVE if code != target), target
            )
            self._from.blockSignals(True)
            self._from.setCurrentIndex(max(0, self._from.findData(other)))
            self._from.blockSignals(False)
        self.changed.emit()

    def _swap(self) -> None:
        source, target = self.pair()
        if source == "auto":
            # Auto-detect has no opposite. Make the current target the source
            # and pick another language to translate into.
            other = next(
                (code for code in languages.ACTIVE if code != target), target
            )
            self.set_pair(target, other)
        else:
            self.set_pair(target, source)
        self.changed.emit()


class GlassCard(glass.Hoverable):
    """A home-screen card: the recipe, sized as a tile, with a hover lift."""

    def __init__(
        self,
        parent: QWidget | None = None,
        accent: bool = False,
    ) -> None:
        super().__init__(parent)
        self._accent = accent
        self.setMinimumSize(280, 210)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(0)
        self.body = layout

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        glass.paint_glass(
            self, painter, self.rect().adjusted(0, 0, -1, -1),
            theme.RADIUS_CARD,
            theme.tint() + (theme.HOVER_LIFT if self._hover else 0.0),
            accent_fill=self._accent,
        )


class AccentSwatch(glass.Hoverable):
    """One of the four accent colours the handoff offers."""

    def __init__(self, colour: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colour = colour
        self.setCheckable(True)
        self.setFixedSize(28, 28)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        painter.setBrush(QColor(self.colour))
        painter.setPen(
            QPen(theme.ink(0.95), 2) if self.isChecked() else QPen(theme.ink(0.25), 1)
        )
        painter.drawEllipse(rect)


class NavItem(glass.Hoverable):
    """One entry in the floating pill. Active is a solid white capsule."""

    def __init__(self, text: str, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setText(text)
        self.setCheckable(True)
        self.setFixedHeight(28)
        self.setMinimumWidth(88)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if self.isChecked():
            painter.fillPath(path, theme.ink(0.96))
            painter.setPen(theme.base())
        else:
            painter.setPen(theme.ink(theme.text_alpha(
                1.0 if self._hover else theme.SECONDARY)))
        painter.setFont(theme.font(13, 600))
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())


class Wordmark(QWidget):
    """The name, top left, in gold, on nothing.

    No panel behind it. A surface would make it one more control on a screen
    that already has six of them, and the name is not a control -- it is the
    product saying what it is.

    It paints its own text rather than wearing a style sheet, so that a change
    of theme is a repaint: the gold that reads as metal over a dark photograph
    is not the gold that survives a bright one.
    """

    #: Twice the size it was, which puts it taller than the bar beside it --
    #: hence the centring rather than a shared top edge.
    SIZE = 48

    def __init__(self, parent: QWidget | None = None, size: int = SIZE) -> None:
        super().__init__(parent)
        clear_fill(self)
        self._font = theme.font(size, 700, tracking=-2)
        metrics = QFontMetrics(self._font)
        self._text = "Linguaflow"
        # Room for the descender of the g: a band cut to the cap height
        # shaves it off, and a clipped letter reads as a broken font.
        self.setFixedSize(
            metrics.horizontalAdvance(self._text) + 6,
            metrics.height() + 6,
        )
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        """A widget that paints itself has to report its own size.

        Without this a bare QWidget answers (-1, -1), and the layout that
        gives the name's width back on the other side of the bar gave back
        minus one pixel -- so the bar sat half a word right of centre.
        """
        return self.size()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setFont(self._font)
        painter.setPen(theme.gold())
        painter.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, self._text)


class NavBar(glass.GlassPanel):
    """The floating pill: the five destinations, centred."""

    chosen = Signal(str)

    #: Screen order. The captions are looked up when the bar is built, not
    #: here: a class body runs at import, before the stored interface
    #: language has been applied, and the nav would stay in Russian while
    #: every other caption changed.
    SCREENS = ("home", "realtime", "upload", "history", "settings")

    @staticmethod
    def captions() -> tuple[tuple[str, str], ...]:
        return (
            ("home", _("Главная")),
            ("realtime", _("Реальное время")),
            ("upload", _("Загрузка")),
            ("history", _("История")),
            ("settings", _("Настройки")),
        )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, radius=theme.RADIUS_PILL, tint=theme.tint(raised=True))
        self.setFixedHeight(theme.NAV_HEIGHT + 16)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(4)
        self._items: dict[str, NavItem] = {}
        for index, (key, text) in enumerate(self.captions()):
            item = NavItem(text, key, self)
            if key == "realtime":
                item.setMinimumWidth(128)
            self._group.addButton(item, index)
            self._items[key] = item
            row.addWidget(item)
        self._group.idClicked.connect(self._emit)
        self.set_active("home")

    def _emit(self, index: int) -> None:
        if 0 <= index < len(self.SCREENS):
            self.chosen.emit(self.SCREENS[index])

    def set_active(self, key: str) -> None:
        item = self._items.get(key)
        if item is not None:
            item.setChecked(True)


class SettingsGroup(glass.GlassPanel):
    """A labelled glass block, the shape every settings section shares."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, radius=theme.RADIUS_CARD)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(14)
        layout.addWidget(glass.eyebrow(title, theme.TERTIARY))
        self.body = layout


def dashed_panel(widget: QWidget, painter: QPainter, radius: int = 28) -> None:
    """The upload dropzone: glass fill, dashed rather than solid edge."""
    rect = widget.rect().adjusted(1, 1, -2, -2)
    path = glass.paint_glass(
        widget, painter, rect, radius, None, border=0.0
    )
    painter.setPen(QPen(theme.ink(0.35), 1.5, Qt.DashLine))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
