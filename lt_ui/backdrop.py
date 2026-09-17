"""The photograph behind everything, and the blurred copy the glass shows.

Qt has no `backdrop-filter`. `QGraphicsBlurEffect` blurs a widget's own
content, not what lies behind it, so the direct translation of the handoff's
recipe does not exist.

What makes the design possible anyway is that nothing moves behind the glass:
the backdrop is one fixed image. So it is blurred once, when the window is
sized, and each panel paints the region of that blurred copy which lies beneath
it. For a static backdrop this is not an approximation of backdrop blur -- it
is the same result, computed ahead of time instead of every frame.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPixmap,
)

from . import theme

ROOT = Path(__file__).resolve().parent.parent
BACKGROUND = ROOT / "assets" / "background.jpg"

#: The blur is computed on a copy this many times smaller. A 24-pixel radius
#: on a downscaled image is visually identical once scaled back -- the result
#: is a blur -- and costs a sixteenth of the work.
DOWNSCALE = 4


def _to_array(image: QImage) -> np.ndarray:
    image = image.convertToFormat(QImage.Format_ARGB32)
    height, width = image.height(), image.width()
    buffer = np.frombuffer(image.constBits(), dtype=np.uint8)
    return buffer.reshape(height, image.bytesPerLine() // 4, 4)[:, :width].astype(
        np.float32
    )


def _to_image(array: np.ndarray) -> QImage:
    array = np.ascontiguousarray(np.clip(array, 0, 255).astype(np.uint8))
    height, width = array.shape[:2]
    return QImage(array.tobytes(), width, height, width * 4, QImage.Format_ARGB32).copy()


def _box_pass(array: np.ndarray, radius: int, axis: int) -> np.ndarray:
    """One box blur along one axis, in linear time via a running sum.

    The obvious `np.convolve` along each line is correct and costs 0.16 s per
    pass at 1280x800 -- about a second for the three passes below, which is why
    the blur runs on a downscaled copy at all. A running sum gives the same
    answer in one traversal, and its cost does not depend on the radius, so how
    frosted the glass is no longer trades against how fast a resize feels.
    """
    if radius < 1:
        return array
    pad = [(0, 0)] * array.ndim
    pad[axis] = (radius + 1, radius)
    padded = np.pad(array, pad, mode="edge")
    zeros = np.zeros_like(np.take(padded, [0], axis=axis))
    cumulative = np.concatenate([zeros, np.cumsum(padded, axis=axis)], axis=axis)

    length = array.shape[axis]
    window = 2 * radius + 1
    upper = np.take(cumulative, range(window, window + length), axis=axis)
    lower = np.take(cumulative, range(0, length), axis=axis)
    return (upper - lower) / window


def blur(image: QImage, radius: int) -> QImage:
    """Three box passes, which is close enough to a Gaussian to read as one."""
    small = image.scaled(
        max(1, image.width() // DOWNSCALE), max(1, image.height() // DOWNSCALE),
        Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
    )
    array = _to_array(small)
    step = max(1, radius // DOWNSCALE)
    for _pass in range(3):
        array = _box_pass(_box_pass(array, step, axis=0), step, axis=1)
    return _to_image(array).scaled(
        image.width(), image.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
    )


def saturate(image: QImage, amount: float) -> QImage:
    """The `saturate(170%)` half of the recipe.

    Without it the blurred copy reads as grey fog; the colour is what makes it
    look like glass over a photograph rather than a frosted sheet.
    """
    array = _to_array(image)
    rgb = array[..., :3]
    grey = rgb.mean(axis=2, keepdims=True)
    array[..., :3] = grey + (rgb - grey) * amount
    array[..., 3] = 255
    return _to_image(array)


class Backdrop:
    """The composed background at one window size, plus its blurred twin."""

    def __init__(self, image_path: Path | str | None = None) -> None:
        self.path = Path(image_path) if image_path else BACKGROUND
        self._source: QImage | None = None
        self.plain = QPixmap()
        self.blurred = QPixmap()
        self._size = (0, 0)

    @property
    def available(self) -> bool:
        return self.path.exists()

    def resize(self, width: int, height: int) -> None:
        if width < 1 or height < 1 or (width, height) == self._size:
            return
        self._size = (width, height)
        canvas = self._compose(width, height)
        self.plain = QPixmap.fromImage(canvas)
        self.blurred = QPixmap.fromImage(
            saturate(blur(canvas, theme.BLUR), theme.SATURATION)
        )

    def _compose(self, width: int, height: int) -> QImage:
        canvas = QImage(width, height, QImage.Format_ARGB32)
        canvas.fill(theme.base())

        if self._source is None and self.available:
            self._source = QImage(str(self.path)).convertToFormat(QImage.Format_ARGB32)

        painter = QPainter(canvas)
        if self._source is not None and not self._source.isNull():
            # Scaled to cover. The handoff pinned its placeholder at
            # `center 130px` so the language bubbles peeked above the cards; in
            # the final artwork those bubbles sit along the bottom, and that
            # offset would push them out of the window entirely.
            source = self._source
            factor = max(width / source.width(), height / source.height())
            scaled = source.scaled(
                round(source.width() * factor), round(source.height() * factor),
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            painter.drawImage(
                QPoint(-(scaled.width() - width) // 2, -(scaled.height() - height) // 2),
                scaled,
            )
        rgb, stops = theme.scrim()
        scrim = QLinearGradient(0, 0, 0, height)
        for position, alpha in zip((0.00, 0.55, 1.00), stops):
            scrim.setColorAt(position, self._veil(rgb, alpha))
        painter.fillRect(QRect(0, 0, width, height), QBrush(scrim))
        painter.end()
        return canvas

    @staticmethod
    def _veil(rgb: tuple[int, int, int], alpha: float) -> QColor:
        colour = QColor(*rgb)
        colour.setAlphaF(alpha)
        return colour

    def invalidate(self) -> None:
        """Force a recompose, for when the mode changed but the size did not."""
        self._size = (0, 0)


_current: Backdrop | None = None


def install(backdrop: Backdrop) -> None:
    global _current
    _current = backdrop


def current() -> Backdrop | None:
    return _current
