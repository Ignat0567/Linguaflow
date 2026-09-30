"""A floating caption window that sits over the meeting, not in it.

Moved independently of the main app, always on top, and able to vanish from a
screen share while remaining on the presenter's display. See lt_ui.affinity.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from . import affinity, glass, theme
from .i18n import _
from .store import Settings, Store


_MIN_W, _MIN_H = 420, 128
_DEFAULT_W, _DEFAULT_H = 720, 168


class OverlayWindow(QWidget):
    """Frameless, translucent, topmost. Drag anywhere that is not a control."""

    closed = Signal()
    share_toggled = Signal(bool)

    def __init__(self, store: Store) -> None:
        super().__init__(None)
        self.store = store
        self.setWindowTitle(_("Linguaflow — субтитры"))
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)

        self._drag: QPoint | None = None
        self._affinity_ok = True
        self._placing = False

        self._last_caption: dict = {}
        self._share = glass.Toggle(self, on=store.settings.overlay_hidden_from_share)
        self._share.toggled.connect(self._on_share)
        self._share_label = _caption(
            _("Скрыто с демонстрации"), 12, 500, theme.SECONDARY
        )
        close = glass.TextLink("✕", self, size=14, alpha=0.7)
        close.clicked.connect(self._close)

        chrome = QHBoxLayout()
        chrome.setContentsMargins(4, 0, 0, 0)
        chrome.setSpacing(10)
        self._chrome_title = _caption(_("Субтитры"), 11, 600, theme.TERTIARY)
        chrome.addWidget(self._chrome_title)
        chrome.addStretch()
        chrome.addWidget(self._share)
        chrome.addWidget(self._share_label)
        chrome.addWidget(close)

        self._speaker = _caption("", 11, 600, theme.TERTIARY)
        self._speaker.setAlignment(Qt.AlignCenter)
        self._speaker.hide()
        self._translated = _fitted(
            _("Субтитры появятся после начала записи"), 28, 16, 600, theme.PRIMARY
        )
        self._original = _fitted("", 14, 11, 400, theme.SECONDARY)
        self._original.hide()

        grip = QSizeGrip(self)
        grip.setFixedSize(16, 16)
        grip.setStyleSheet("background: transparent;")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 14, 16, 12)
        root.setSpacing(6)
        root.addLayout(chrome)
        root.addWidget(self._speaker)
        # The translation gets the larger share of whatever height the user
        # gave the window; neither may push past it.
        root.addWidget(self._translated, 3)
        root.addWidget(self._original, 2)
        grip_row = QHBoxLayout()
        grip_row.addStretch()
        grip_row.addWidget(grip)
        root.addLayout(grip_row)

        self._place(store.settings)

    # -- public ----------------------------------------------------------
    def reveal(self) -> None:
        self._place(self.store.settings)
        self.show()
        self._apply_affinity()
        self.raise_()

    def set_caption(
        self,
        original: str = "",
        translated: str = "",
        speaker: str | None = None,
        listening: bool = False,
    ) -> None:
        self._last_caption = {
            "original": original, "translated": translated,
            "speaker": speaker, "listening": listening,
        }
        if speaker:
            self._speaker.setText(speaker)
            self._speaker.show()
        else:
            self._speaker.hide()

        main = translated.strip() or original.strip()
        if main:
            self._translated.setText(main)
            self._translated.setStyleSheet(_colour(theme.PRIMARY))
        elif listening:
            self._translated.setText(_("Слушаю…"))
            self._translated.setStyleSheet(_colour(theme.MUTED))
        else:
            self._translated.setText(_("Субтитры появятся после начала записи"))
            self._translated.setStyleSheet(_colour(theme.MUTED))

        # When the translation is up, the original sits underneath as a check.
        # When there is no translation yet, the original already occupies the
        # main line and repeating it would just double the same words.
        if translated.strip() and original.strip():
            self._original.setText(original.strip())
            self._original.show()
        else:
            self._original.hide()

    # -- affinity --------------------------------------------------------
    def _on_share(self, hidden: bool) -> None:
        self.store.settings.overlay_hidden_from_share = hidden
        self.store.save_settings()
        self._share_label.setText(
            _("Скрыто с демонстрации") if hidden else _("Видно на демонстрации")
        )
        if self.isVisible():
            self._apply_affinity()
        self.share_toggled.emit(hidden)

    def _apply_affinity(self) -> None:
        hwnd = int(self.winId())
        hidden = self.store.settings.overlay_hidden_from_share
        ok = affinity.apply(hwnd, hidden)
        self._affinity_ok = ok
        if hidden and not ok:
            self._share_label.setText(_("Не удалось скрыть с захвата"))

    # -- placement -------------------------------------------------------
    def _place(self, settings: Settings) -> None:
        width = max(_MIN_W, settings.overlay_w)
        height = max(_MIN_H, settings.overlay_h)
        self._placing = True
        try:
            if settings.overlay_x < 0 or settings.overlay_y < 0:
                area = _available()
                x = area.center().x() - width // 2
                y = area.bottom() - height - 48
                self.setGeometry(x, y, width, height)
            else:
                rect = QRect(settings.overlay_x, settings.overlay_y, width, height)
                self.setGeometry(_clamp_to_screens(rect))
        finally:
            self._placing = False

    def _remember(self) -> None:
        geo = self.geometry()
        self.store.settings.overlay_x = geo.x()
        self.store.settings.overlay_y = geo.y()
        self.store.settings.overlay_w = geo.width()
        self.store.settings.overlay_h = geo.height()
        self.store.save_settings()

    def _close(self) -> None:
        self.store.settings.overlay = False
        self._remember()
        self.hide()
        self.closed.emit()

    # -- window events ---------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_affinity()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._remember()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._placing:
            self._remember()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._drag is not None:
            self._drag = None
            self._remember()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def restyle(self) -> None:
        """Re-apply captions after the app's theme or language changed.

        The plate stays dark either way; what this fixes is `theme.restyle`
        having walked in and recoloured these labels along with the rest.
        """
        self.setWindowTitle(_("Linguaflow — субтитры"))
        self._chrome_title.setText(_("Субтитры"))
        hidden = self.store.settings.overlay_hidden_from_share
        self._share_label.setText(
            _("Скрыто с демонстрации") if hidden else _("Видно на демонстрации")
        )
        self.set_caption(**self._last_caption)
        for label, alpha in (
            (self._chrome_title, theme.TERTIARY),
            (self._share_label, theme.TERTIARY),
            (self._speaker, theme.TERTIARY),
        ):
            label.setStyleSheet(_colour(alpha))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)
        fill = QColor(theme.INK)
        fill.setAlpha(210)
        painter.fillPath(path, fill)
        painter.setPen(QPen(theme.white(0.22), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


def _caption(text: str, size: int, weight: int, alpha: float) -> QLabel:
    """A caption on the overlay's own dark plate.

    Always white, whatever theme the app is in. The overlay does not sit on
    the app's backdrop -- it sits over someone else's video call, where a
    plate dark enough to read against is the only thing that works. Taking
    the light theme's near-black text here would have put black letters on a
    near-black plate.
    """
    widget = glass.label(text, size, weight, alpha, wrap=True)
    widget.setStyleSheet(_colour(alpha))
    widget.setProperty(theme.ALPHA_PROPERTY, None)
    widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    return widget


class FitLabel(QLabel):
    """Wrapped text that always fits the label's own rectangle.

    The window is the size the user dragged it to, and a long sentence at
    28 px ran out of the bottom of it: the second line cut in half, the rest
    gone. The text is set in the largest size between `largest` and
    `smallest` that fits; when even the smallest does not, the beginning is
    dropped for «…» -- in a subtitle the words just said are the ones that
    matter.
    """

    def __init__(self, largest: int, smallest: int, weight: int) -> None:
        super().__init__()
        self.largest = largest
        self.smallest = smallest
        self.weight = weight
        self._full = ""
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(1, 1)

    # The layout must not size the window to the text; the text fits the
    # window.
    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.largest * 8, self.largest * 2)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(1, 1)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return False

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self._fit()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event) -> None:  # noqa: N802
        # Shown again at the size it had when hidden, it gets no resize:
        # the original under the translation came back unfitted and clipped.
        super().showEvent(event)
        self._fit()

    def _fits(self, text: str, size: int) -> bool:
        metrics = QFontMetrics(theme.font(size, self.weight))
        box = metrics.boundingRect(
            QRect(0, 0, max(1, self.width()), 100_000),
            int(Qt.AlignCenter | Qt.TextWordWrap), text,
        )
        return box.height() <= self.height() and box.width() <= self.width()

    def _fit(self) -> None:
        text = self._full
        size = self.largest
        if not self.isVisible() or self.height() < 4:
            # Not laid out yet: there is nothing to fit to, and trimming to
            # a zero-sized box would throw the text away. The resize that
            # comes with showing it fits it.
            self.setFont(theme.font(size, self.weight))
            super().setText(text)
            return
        while size > self.smallest and not self._fits(text, size):
            size -= 1
        if text and not self._fits(text, size):
            words = text.split()
            low, high = 1, len(words)
            # The most words from the end that still fit.
            while low < high:
                middle = (low + high + 1) // 2
                if self._fits("… " + " ".join(words[-middle:]), size):
                    low = middle
                else:
                    high = middle - 1
            text = "… " + " ".join(words[-low:])
        self.setFont(theme.font(size, self.weight))
        super().setText(text)


def _fitted(text: str, largest: int, smallest: int, weight: int, alpha: float) -> FitLabel:
    widget = FitLabel(largest, smallest, weight)
    widget.setStyleSheet(_colour(alpha))
    widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    widget.setText(text)
    return widget


def _colour(alpha: float) -> str:
    return f"color: rgba(255,255,255,{alpha:.3f}); background: transparent;"


def _available() -> QRect:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return QRect(0, 0, 1280, 800)
    return screen.availableGeometry()


def _clamp_to_screens(rect: QRect) -> QRect:
    """Keep the overlay on a monitor after a layout change.

    A saved position on a disconnected display would otherwise open the
    window somewhere the user cannot grab it.
    """
    screens = QGuiApplication.screens()
    if not screens:
        return rect
    for screen in screens:
        area = screen.availableGeometry()
        if area.intersects(rect):
            x = min(max(rect.x(), area.x()), area.right() - min(rect.width(), area.width()))
            y = min(max(rect.y(), area.y()), area.bottom() - min(rect.height(), area.height()))
            return QRect(x, y, rect.width(), rect.height())
    area = screens[0].availableGeometry()
    return QRect(area.center().x() - rect.width() // 2, area.bottom() - rect.height() - 48,
                 rect.width(), rect.height())
