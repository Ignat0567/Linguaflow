"""The glass surface, and everything built on it.

One recipe -- tint, blur beneath, hairline border -- and
every card, pill, chip and toggle in the app is that recipe at a different
size. It is written once here so that a new screen cannot quietly invent its
own shade of white.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QBrush,
    QConicalGradient,
    QCursor,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QWidget,
)

from . import backdrop as backdrop_module
from . import theme


def paint_glass(
    widget: QWidget,
    painter: QPainter,
    rect: QRect,
    radius: int,
    tint: float | None = None,
    accent_fill: bool = False,
    border: float | None = None,
    lift: float = 0.0,
) -> QPainterPath:
    """Paint the handoff's glass recipe into `rect` of `widget`.

    `tint` and `border` default to whatever the current mode asks for, and
    are resolved here rather than in the signature: a default argument is
    bound once at import, which would freeze the app in the mode it started
    in.

    `lift` is the pointer's answer, laid over whichever fill was used. It was
    once added to `tint` by each caller, which worked on a plain surface and
    did nothing at all on an accent one, because the accent gradient never
    reads `tint` -- so the home screen's first card, the one filled with the
    accent, was the only card on it that ignored the mouse.
    """
    if tint is None:
        tint = theme.tint()
    if radius >= theme.RADIUS_PILL:
        radius = rect.height() // 2
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)

    painter.setRenderHint(QPainter.Antialiasing)
    painter.save()
    painter.setClipPath(path)

    backdrop = backdrop_module.current()
    if backdrop is not None and not backdrop.blurred.isNull():
        # Where this widget sits in the window is where it must sample from,
        # otherwise the blur slides against the photograph as panels move.
        origin = widget.mapTo(widget.window(), rect.topLeft())
        painter.drawPixmap(rect, backdrop.blurred, QRect(origin, rect.size()))

    if accent_fill:
        gradient = QLinearGradient(QPointF(rect.topLeft()), QPointF(rect.bottomRight()))
        gradient.setColorAt(0.0, theme.accent(0.55))
        gradient.setColorAt(1.0, theme.surface(0.10))
        painter.fillPath(path, QBrush(gradient))
    else:
        painter.fillPath(path, theme.surface(tint))

    if lift:
        painter.fillPath(path, theme.white(lift))

    painter.restore()

    edge = theme.border_colour() if border is None else theme.ink(border)
    painter.setPen(QPen(edge, 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    return path


class GlassPanel(QWidget):
    """A container that paints itself as glass."""

    def __init__(
        self,
        parent: QWidget | None = None,
        radius: int = theme.RADIUS_PANEL,
        tint: float | None = None,
        accent_fill: bool = False,
    ) -> None:
        super().__init__(parent)
        self.radius = radius
        self.tint = tint
        self.accent_fill = accent_fill
        #: Raised while the pointer is over it; see `clickable`.
        self.lift = 0.0

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt spells it this way
        painter = QPainter(self)
        paint_glass(
            self,
            painter,
            self.rect().adjusted(0, 0, -1, -1),
            self.radius,
            self.tint,
            self.accent_fill,
            lift=self.lift,
        )


class Hoverable(QAbstractButton):
    """Shared hover bookkeeping.

    The handoff draws no hover state and says so explicitly, leaving it to
    implementation. A surface that does not answer the pointer feels broken,
    so every control here brightens by the +4% white it suggests.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hover = False
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setAttribute(Qt.WA_Hover, True)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()


class GlassButton(Hoverable):
    """A pill button: glass by default, filled with the accent when primary."""

    def __init__(
        self,
        text: str,
        parent: QWidget | None = None,
        primary: bool = False,
        size: int = 13,
        height: int = 38,
        padding: int = 22,
    ) -> None:
        super().__init__(parent)
        self._size = size
        self._padding = padding
        self.primary = primary
        self.setText(text)
        self.setFixedHeight(height)
        self.setFocusPolicy(Qt.StrongFocus)

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        metrics = QFontMetrics(theme.font(self._size, 600))
        self.setMinimumWidth(metrics.horizontalAdvance(text) + self._padding * 2)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = rect.height() / 2
        if self.primary:
            painter.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), radius, radius)
            painter.fillPath(path, theme.accent(0.88 if self._hover else 1.0))
            painter.setPen(theme.on_accent())
        else:
            paint_glass(
                self, painter, rect, theme.RADIUS_PILL,
                lift=theme.HOVER_LIFT if self._hover else 0.0,
            )
            painter.setPen(theme.ink(theme.PRIMARY))
        if self.hasFocus():
            pen = painter.pen()
            painter.setPen(QPen(theme.accent(0.9), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1), radius, radius)
            painter.setPen(pen)
        painter.setFont(theme.font(self._size, 600))
        painter.drawText(rect, Qt.AlignCenter, self.text())


class TextLink(Hoverable):
    """A bare text action: the handoff's arrows and reset links."""

    def __init__(
        self,
        text: str,
        parent: QWidget | None = None,
        size: int = 13,
        alpha: float = theme.SECONDARY,
    ) -> None:
        super().__init__(parent)
        self.setText(text)
        self._size = size
        self._alpha = alpha
        metrics = QFontMetrics(theme.font(size, 500))
        self.setFixedSize(metrics.horizontalAdvance(text) + 10, metrics.height() + 8)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setFont(theme.font(self._size, 500))
        painter.setPen(theme.ink(theme.text_alpha(
            1.0 if self._hover else self._alpha)))
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())


class Toggle(Hoverable):
    """The 38x21 pill switch, knob sliding from 2px to 19px."""

    def __init__(self, parent: QWidget | None = None, on: bool = False) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(on)
        self.setFixedSize(38, 21)
        self._position = 19.0 if on else 2.0
        self._animation = QPropertyAnimation(self, b"knob", self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._slide)

    def _slide(self, on: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(19.0 if on else 2.0)
        self._animation.start()

    def get_knob(self) -> float:
        return self._position

    def set_knob(self, value: float) -> None:
        self._position = value
        self.update()

    knob = Property(float, get_knob, set_knob)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        lift = theme.HOVER_LIFT if self._hover else 0.0
        if self.isChecked():
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), rect.height() / 2, rect.height() / 2)
            painter.fillPath(path, theme.accent(0.95))
            if lift:
                painter.fillPath(path, theme.white(lift))
        else:
            paint_glass(self, painter, rect, theme.RADIUS_PILL, lift=lift)
        # On the accent fill a white knob reads; on a pale glass panel in
        # light mode it disappears into the panel.
        lit = self.isChecked() or not theme.is_light()
        knob = theme.white(0.98) if lit else theme.ink(0.45)
        painter.setBrush(knob)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(self._position + 8.5, rect.height() / 2), 8.5, 8.5)


class Chip(Hoverable):
    """One option in a segmented group: formats, voices, live modes."""

    def __init__(
        self,
        text: str,
        parent: QWidget | None = None,
        size: int = 13,
        height: int = 34,
        padding: int = 17,
    ) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self._size = size
        self.setFixedHeight(height)
        metrics = QFontMetrics(theme.font(size, 600))
        self.setMinimumWidth(metrics.horizontalAdvance(text) + padding * 2)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = self.rect().adjusted(0, 0, -1, -1)
        if self.isChecked():
            painter.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), rect.height() / 2, rect.height() / 2)
            # A chosen chip is already solid, so it brightens by going fully
            # opaque rather than by taking more white.
            painter.fillPath(path, theme.ink(1.0 if self._hover else 0.94))
            painter.setPen(theme.base())
        else:
            painter.setPen(theme.ink(theme.text_alpha(
                0.88 if self._hover else theme.SECONDARY)))
        painter.setFont(theme.font(self._size, 600))
        painter.drawText(rect, Qt.AlignCenter, self.text())


class GlassSelect(QComboBox):
    """A picker that looks like the rest of the glass.

    QComboBox draws through the style sheet rather than a paintEvent, so this
    is the one surface expressed in Qt's dialect of CSS instead of the shared
    recipe. Its popup is opaque, which is what the handoff specifies for a
    dropdown (`#0d0f1a`) -- a translucent list over a translucent panel is
    unreadable.
    """

    DARK = """
    QComboBox {
        background: rgba(255,255,255,0.10);
        border: 1px solid rgba(255,255,255,0.20);
        border-radius: 19px;
        padding: 0 34px 0 18px;
        color: rgba(255,255,255,0.95);
    }
    QComboBox:hover { background: rgba(255,255,255,0.14); }
    QComboBox:focus { border: 1px solid rgba(127,164,255,0.85); }
    QComboBox::drop-down { border: none; width: 26px; }
    QComboBox::down-arrow { image: none; }
    QComboBox QAbstractItemView {
        background: #0d0f1a;
        border: 1px solid rgba(255,255,255,0.18);
        border-radius: 12px;
        color: rgba(255,255,255,0.92);
        selection-background-color: rgba(127,164,255,0.35);
        padding: 6px;
        outline: none;
    }
    """

    LIGHT = """
    QComboBox {
        background: rgba(255,255,255,0.72);
        border: 1px solid rgba(13,15,26,0.14);
        border-radius: 19px;
        padding: 0 34px 0 18px;
        color: rgba(13,15,26,0.95);
    }
    QComboBox:hover { background: rgba(255,255,255,0.86); }
    QComboBox:focus { border: 1px solid rgba(90,125,215,0.85); }
    QComboBox::drop-down { border: none; width: 26px; }
    QComboBox::down-arrow { image: none; }
    QComboBox QAbstractItemView {
        background: #ffffff;
        border: 1px solid rgba(13,15,26,0.14);
        border-radius: 12px;
        color: rgba(13,15,26,0.92);
        selection-background-color: rgba(127,164,255,0.35);
        padding: 6px;
        outline: none;
    }
    """

    @classmethod
    def style_for_mode(cls) -> str:
        return cls.LIGHT if theme.is_light() else cls.DARK

    def __init__(self, parent: QWidget | None = None, width: int = 150) -> None:
        super().__init__(parent)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFont(theme.font(14, 500))
        self.setFixedHeight(38)
        self.setMinimumWidth(width)
        self.setStyleSheet(self.style_for_mode())

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        # The style sheet removes the platform arrow, so the chevron is drawn
        # here, in the flat shapes the handoff uses instead of an icon set.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.ink(0.55), 1.6))
        x, y = self.width() - 24, self.height() // 2 - 2
        painter.drawLine(x, y, x + 5, y + 5)
        painter.drawLine(x + 5, y + 5, x + 10, y)


class GlassInput(QLineEdit):
    """A text field on glass, for the few things that must be typed.

    Like the picker, it is styled rather than painted: QLineEdit draws its
    own text, selection and caret, and taking that over to gain a blurred
    backdrop would cost more than the backdrop is worth on a field this size.
    """

    DARK = """
    QLineEdit {
        background: rgba(255,255,255,0.10);
        border: 1px solid rgba(255,255,255,0.20);
        border-radius: 17px;
        padding: 0 16px;
        color: rgba(255,255,255,0.95);
        selection-background-color: rgba(127,164,255,0.45);
    }
    QLineEdit:hover { background: rgba(255,255,255,0.14); }
    QLineEdit:focus { border: 1px solid rgba(127,164,255,0.85); }
    """

    LIGHT = """
    QLineEdit {
        background: rgba(255,255,255,0.72);
        border: 1px solid rgba(13,15,26,0.14);
        border-radius: 17px;
        padding: 0 16px;
        color: rgba(13,15,26,0.95);
        selection-background-color: rgba(127,164,255,0.45);
    }
    QLineEdit:hover { background: rgba(255,255,255,0.86); }
    QLineEdit:focus { border: 1px solid rgba(90,125,215,0.85); }
    """

    @classmethod
    def style_for_mode(cls) -> str:
        return cls.LIGHT if theme.is_light() else cls.DARK

    def __init__(self, parent: QWidget | None = None, placeholder: str = "") -> None:
        super().__init__(parent)
        self.setFont(theme.font(13, 400))
        self.setFixedHeight(34)
        self.setPlaceholderText(placeholder)
        self.setStyleSheet(self.style_for_mode())


class RecordButton(Hoverable):
    """The 96px circle, with the handoff's two expanding rings while live."""

    RING_PERIOD_MS = 1800
    FRAME_MS = 33

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(150, 150)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._advance)
        self.toggled.connect(self._run_rings)

    def _run_rings(self, on: bool) -> None:
        if on:
            self._phase = 0.0
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _advance(self) -> None:
        self._phase = (self._phase + self.FRAME_MS / self.RING_PERIOD_MS) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        centre = QPointF(self.width() / 2, self.height() / 2)

        if self.isChecked():
            # Two rings, the second a third of a period behind, each expanding
            # from the button's edge and fading as it goes.
            for offset in (0.0, 0.33):
                progress = (self._phase + offset) % 1.0
                radius = 48 + progress * 26
                painter.setPen(QPen(theme.accent(0.45 * (1.0 - progress)), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(centre, radius, radius)

        body = QRect(int(centre.x()) - 48, int(centre.y()) - 48, 96, 96)
        # The widget is 150px and the circle 96, and the whole 150 is what a
        # click lands on -- so the whole 150 is what answers the pointer.
        lift = theme.HOVER_LIFT if self._hover else 0.0
        if self.isChecked():
            painter.setBrush(theme.accent(0.95))
            painter.setPen(QPen(theme.ink(0.30), 1))
            painter.drawEllipse(body)
            if lift:
                painter.setBrush(theme.white(lift))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(body)
                painter.setPen(QPen(theme.ink(0.30), 1))
            painter.setBrush(theme.on_accent())
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(
                QRect(body.center().x() - 10, body.center().y() - 10, 22, 22), 5, 5
            )
        else:
            paint_glass(self, painter, body, body.height() // 2,
                        theme.tint(raised=True), lift=lift)
            painter.setBrush(theme.ink(0.92))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(body.center()), 17, 17)


class ProgressRing(QWidget):
    """`conic-gradient(accent N%, rgba(255,255,255,0.15) 0)`, with a glass core."""

    def __init__(self, parent: QWidget | None = None, diameter: int = 160) -> None:
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self._value = 0.0

    def set_value(self, fraction: float) -> None:
        self._value = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)

        stop = max(1e-4, min(1.0, self._value))
        gradient = QConicalGradient(QPointF(rect.center()), 90.0)
        gradient.setColorAt(0.0, theme.accent(0.95))
        gradient.setColorAt(max(0.0, stop - 0.002), theme.accent(0.95))
        empty = theme.ink(0.15)
        gradient.setColorAt(stop, empty)
        gradient.setColorAt(1.0, empty)

        # A conical gradient sweeps anticlockwise from its start angle, so the
        # ring is mirrored to fill the way a clock face does.
        painter.save()
        painter.translate(rect.center())
        painter.scale(-1, 1)
        painter.translate(-rect.center().x(), -rect.center().y())
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(rect)
        painter.restore()

        inner = rect.adjusted(18, 18, -18, -18)
        paint_glass(self, painter, inner, inner.width() // 2, theme.tint(raised=True))
        painter.setFont(theme.font(30, 700, tracking=-2))
        painter.setPen(theme.ink(theme.PRIMARY))
        painter.drawText(inner, Qt.AlignCenter, f"{round(self._value * 100)}%")


# -- text ----------------------------------------------------------------


def label(
    text: str,
    size: int,
    weight: int = 400,
    alpha: float = theme.PRIMARY,
    tracking: float = 0.0,
    uppercase: bool = False,
    wrap: bool = False,
) -> QLabel:
    widget = QLabel(text.upper() if uppercase else text)
    widget.setFont(theme.font(size, weight, tracking))
    widget.setProperty(theme.ALPHA_PROPERTY, alpha)
    widget.setStyleSheet(theme.label_colour(alpha))
    widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    widget.setWordWrap(wrap)
    if not wrap:
        widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return widget


def eyebrow(text: str, alpha: float = theme.SECONDARY) -> QLabel:
    """The 11px uppercase label with wide tracking, used as a section marker."""
    return label(text, 11, 600, alpha, tracking=10, uppercase=True)


def clickable(widget: QWidget, action: Callable[[], None]) -> QWidget:
    """Make a panel behave like the card the handoff draws it as.

    Including under the pointer: a cursor that turns into a hand over a
    surface that then does nothing reads as a card that failed to load, not
    as one waiting to be clicked.
    """
    widget.setCursor(QCursor(Qt.PointingHandCursor))
    widget.setAttribute(Qt.WA_Hover, True)

    def press(event) -> None:
        if event.button() == Qt.LeftButton:
            action()

    def enter(event) -> None:
        widget.lift = theme.HOVER_LIFT
        widget.update()

    def leave(event) -> None:
        widget.lift = 0.0
        widget.update()

    widget.mousePressEvent = press  # type: ignore[method-assign]
    if hasattr(widget, "lift"):
        widget.enterEvent = enter  # type: ignore[method-assign]
        widget.leaveEvent = leave  # type: ignore[method-assign]
    return widget
