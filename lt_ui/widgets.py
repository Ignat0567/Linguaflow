"""Composite controls built from the glass primitives.

The primitives in glass.py are the recipe. These are the pieces the screens
actually place: a language pair, a chip group, a clickable card, the nav.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QPixmap,
    QLinearGradient,
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
            accent_fill=self._accent,
            lift=theme.HOVER_LIFT if self._hover else 0.0,
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
        # Unchosen swatches sit behind a hairline; under the pointer that line
        # comes forward, so the one being considered is visibly the one the
        # click would take.
        if self.isChecked():
            painter.setPen(QPen(theme.ink(0.95), 2))
        else:
            painter.setPen(QPen(theme.ink(0.55 if self._hover else 0.25),
                                2 if self._hover else 1))
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
    """The name, top left: the supplied logotype where there is one.

    The lettering used to be drawn here -- a script face filled with a
    metallic ramp, extruded and bevelled. That was an approximation of a
    thing the designer had already made, so the made thing wins and the
    drawing stays behind it as a fallback: a missing or unreadable file
    leaves a wordmark rather than a gap.

    The image is trimmed of its transparent margins before it ships, so its
    height on screen is the height of the letters and not of whatever canvas
    they were exported on.
    """

    #: How tall the logotype stands. The bar beside it is 60, and the name is
    #: allowed to be the larger of the two.
    HEIGHT = 74

    #: The drawn fallback, in pixels of font size.
    SIZE = 58
    DEPTH = 3
    SHADOW_STEPS = 5

    SOURCE = Path(__file__).resolve().parent.parent / "assets" / "wordmark.png"

    def __init__(self, parent: QWidget | None = None, size: int = SIZE) -> None:
        super().__init__(parent)
        clear_fill(self)
        self._text = "Linguaflow"
        self._font = theme.mark_font(size)
        metrics = QFontMetrics(self._font)
        self._baseline = metrics.ascent() + 4
        self._lead = 10.0

        self._logo = self._load()
        if self._logo is not None:
            self.setFixedSize(self._logo.width(), self._logo.height())
        else:
            self.setFixedSize(
                int(metrics.horizontalAdvance(self._text) + self._lead * 2
                    + self.DEPTH),
                metrics.height() + self.DEPTH + 10,
            )
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _load(self) -> QPixmap | None:
        """The logotype at the height it will be drawn, or nothing.

        Scaled once here rather than on every repaint: a 840-pixel image
        resampled smoothly on each paint is work repeated for no gain, since
        the size never changes.
        """
        if not self.SOURCE.exists():
            return None
        image = QPixmap(str(self.SOURCE))
        if image.isNull():
            return None
        return image.scaledToHeight(
            self.HEIGHT, Qt.SmoothTransformation
        )

    @property
    def uses_logo(self) -> bool:
        return self._logo is not None

    def sizeHint(self) -> QSize:  # noqa: N802
        """A widget that paints itself has to report its own size.

        Without this a bare QWidget answers (-1, -1), and the layout that
        gives the name's width back on the other side of the bar gave back
        minus one pixel -- so the bar sat half a word right of centre.
        """
        return self.size()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._logo is not None:
            painter.drawPixmap(0, 0, self._logo)
            return
        self._paint_lettering(painter)

    # -- the fallback ----------------------------------------------------
    def _path(self) -> QPainterPath:
        path = QPainterPath()
        path.addText(self._lead, float(self._baseline), self._font, self._text)
        return path

    def _paint_lettering(self, painter: QPainter) -> None:
        """Struck in gold by hand, for when the logotype is not there."""
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        letters = self._path()
        top = letters.boundingRect().top()
        height = max(1.0, letters.boundingRect().height())

        painter.setPen(Qt.NoPen)
        for step in range(self.SHADOW_STEPS, 0, -1):
            painter.setBrush(QColor(0, 0, 0, 16))
            painter.drawPath(letters.translated(step * 0.7, step * 0.9))

        painter.setBrush(theme.GOLD_EDGE)
        for step in range(self.DEPTH, 0, -1):
            painter.drawPath(letters.translated(step * 0.8, step * 0.8))

        ramp = QLinearGradient(0.0, top, 0.0, top + height)
        for position, colour in theme.gold_ramp():
            ramp.setColorAt(position, QColor(colour))
        painter.setBrush(ramp)
        painter.drawPath(letters)

        painter.save()
        painter.setClipPath(letters)
        lit = QLinearGradient(0.0, top, 0.0, top + height * 0.22)
        lit.setColorAt(0.0, QColor(255, 255, 255, 150))
        lit.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(lit)
        painter.drawPath(letters)
        painter.restore()

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(theme.GOLD_EDGE, 0.8))
        painter.drawPath(letters)


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
