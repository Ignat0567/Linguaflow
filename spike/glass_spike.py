"""Can Qt render the handoff's Liquid Glass panels?

The design is specified in CSS terms: `backdrop-filter: blur(24px)
saturate(170%)` over a full-bleed photograph. Qt has no backdrop-filter, and
QGraphicsBlurEffect blurs a widget's own content rather than what sits behind
it, so the obvious translation does not exist.

The way through is that nothing moves behind the glass. The background is one
fixed image. So the blur can be computed once, at startup, and each panel
simply paints the region of the pre-blurred image that lies beneath it, plus
the tint, border and inner highlight the handoff specifies. The result is not
an approximation of backdrop blur -- for a static backdrop it is the same
thing.

This renders one screen to a PNG so the claim can be looked at rather than
believed.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
BACKGROUND = ROOT / "design" / "design_handoff_linguaflow" / "assets" / "bg-translate.png"
OUT = ROOT / "spike" / "glass_preview.png"

WIDTH, HEIGHT = 1280, 800
ACCENT = QColor("#7fa4ff")


def blur(image: QImage, radius: int) -> QImage:
    """Box blur, run three times, which approximates a Gaussian closely.

    Done on a downscaled copy and scaled back: a 24-pixel radius on a 1280-wide
    image costs nothing this way and is visually indistinguishable, because the
    result is a blur.
    """
    scale = 4
    small = image.scaled(
        image.width() // scale, image.height() // scale,
        Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
    ).convertToFormat(QImage.Format_ARGB32)

    step = max(1, radius // scale)
    for _ in range(3):
        small = _box_pass(small, step)
    return small.scaled(
        image.width(), image.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
    )


def _box_pass(image: QImage, radius: int) -> QImage:
    import numpy as np

    width, height = image.width(), image.height()
    pointer = image.bits()
    array = np.frombuffer(pointer, dtype=np.uint8).reshape(height, width, 4).astype(
        np.float32
    )

    window = radius * 2 + 1
    kernel = np.ones(window, dtype=np.float32) / window
    for axis in (0, 1):
        padded = np.pad(
            array,
            [(radius, radius) if a == axis else (0, 0) for a in range(3)],
            mode="edge",
        )
        array = np.apply_along_axis(
            lambda line: np.convolve(line, kernel, mode="valid"), axis, padded
        )

    out = QImage(
        np.ascontiguousarray(array.astype(np.uint8)).tobytes(),
        width, height, QImage.Format_ARGB32,
    )
    return out.copy()


def saturate(image: QImage, amount: float) -> QImage:
    import numpy as np

    width, height = image.width(), image.height()
    array = np.frombuffer(image.bits(), dtype=np.uint8).reshape(
        height, width, 4
    ).astype(np.float32)
    rgb = array[..., :3]
    grey = rgb.mean(axis=2, keepdims=True)
    array[..., :3] = np.clip(grey + (rgb - grey) * amount, 0, 255)
    out = QImage(
        np.ascontiguousarray(array.astype(np.uint8)).tobytes(),
        width, height, QImage.Format_ARGB32,
    )
    return out.copy()


def glass_panel(
    painter: QPainter,
    blurred: QImage,
    rect: QRect,
    radius: int,
    tint: float = 0.08,
    accent_fill: bool = False,
) -> None:
    """One panel, exactly as the handoff's recipe describes it."""
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    painter.save()
    painter.setClipPath(path)
    # What is behind the panel, already blurred and saturated.
    painter.drawImage(rect, blurred, rect)

    if accent_fill:
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        start = QColor(ACCENT)
        start.setAlphaF(0.55)
        gradient.setColorAt(0.0, start)
        gradient.setColorAt(1.0, QColor(255, 255, 255, 26))
        painter.fillPath(path, QBrush(gradient))
    else:
        painter.fillPath(path, QColor(255, 255, 255, int(255 * tint)))
    painter.restore()

    # Inset highlight along the top edge, then the hairline border.
    painter.save()
    painter.setClipPath(path)
    highlight = QPainterPath()
    highlight.addRoundedRect(
        QRect(rect.x(), rect.y(), rect.width(), 2), radius, radius
    )
    painter.fillPath(highlight, QColor(255, 255, 255, 80))
    painter.restore()

    painter.setPen(QPen(QColor(255, 255, 255, 48), 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)


def text(painter: QPainter, x: int, y: int, body: str, size: int,
         weight: int = 400, alpha: int = 255, tracking: float = 0.0) -> None:
    font = QFont("Segoe UI", size)
    font.setWeight(QFont.Weight(weight))
    if tracking:
        font.setLetterSpacing(QFont.PercentageSpacing, 100 + tracking)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, alpha))
    painter.drawText(QPoint(x, y), body)


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841 -- required before QImage work

    if not BACKGROUND.exists():
        print(f"Нет фона: {BACKGROUND}")
        return 1

    source = QImage(str(BACKGROUND)).convertToFormat(QImage.Format_ARGB32)
    # background-size: 145% auto; background-position: center 130px;
    scaled = source.scaled(
        int(WIDTH * 1.45), int(WIDTH * 1.45 * source.height() / source.width()),
        Qt.KeepAspectRatio, Qt.SmoothTransformation,
    )

    canvas = QImage(WIDTH, HEIGHT, QImage.Format_ARGB32)
    canvas.fill(QColor("#04060c"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.drawImage(QPoint(-(scaled.width() - WIDTH) // 2, 130 - 300), scaled)
    painter.end()

    # The scrim the handoff specifies, over the photograph.
    painter = QPainter(canvas)
    scrim = QLinearGradient(0, 0, 0, HEIGHT)
    scrim.setColorAt(0.00, QColor(4, 6, 14, int(255 * 0.55)))
    scrim.setColorAt(0.55, QColor(4, 6, 14, int(255 * 0.72)))
    scrim.setColorAt(1.00, QColor(4, 6, 14, int(255 * 0.88)))
    painter.fillRect(QRect(0, 0, WIDTH, HEIGHT), QBrush(scrim))
    painter.end()

    import time

    started = time.perf_counter()
    blurred = saturate(blur(canvas, 24), 1.7)
    print(f"blur+saturate of {WIDTH}x{HEIGHT}: {time.perf_counter() - started:.2f}s")

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)

    # Pill nav.
    glass_panel(painter, blurred, QRect(390, 28, 500, 44), 22, tint=0.09)
    items = ["Главная", "Реальное время", "Загрузка", "История", "Настройки"]
    x = 404
    for index, item in enumerate(items):
        width = 18 + len(item) * 7
        if index == 0:
            active = QPainterPath()
            active.addRoundedRect(QRect(x - 6, 36, width + 12, 28), 14, 14)
            painter.fillPath(active, QColor(255, 255, 255, 235))
            painter.setPen(QColor("#0d0f1a"))
        else:
            painter.setPen(QColor(255, 255, 255, 190))
        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        painter.drawText(QRect(x - 6, 36, width + 12, 28), Qt.AlignCenter, item)
        x += width + 18

    text(painter, 340, 190, "Что переводим сегодня?", 30, 700)
    text(painter, 340, 222, "Речь, видео и файлы на восьми языках.", 11, 400, 190)

    # Two cards, the first accent-filled.
    glass_panel(painter, blurred, QRect(200, 260, 420, 210), 22, accent_fill=True)
    text(painter, 228, 296, "01 · LIVE", 8, 600, 220, tracking=12)
    text(painter, 228, 336, "Перевод в реальном времени", 17, 700)
    text(painter, 228, 366, "Живые субтитры и озвучка", 10, 400, 200)
    text(painter, 228, 440, "Начать →", 11, 600)

    glass_panel(painter, blurred, QRect(650, 260, 420, 210), 22)
    text(painter, 678, 296, "02 · FILE", 8, 600, 180, tracking=12)
    text(painter, 678, 336, "Загрузка файла", 17, 700)
    text(painter, 678, 366, "Видео, аудио, подкаст", 10, 400, 200)
    text(painter, 678, 440, "Загрузить →", 11, 600)

    text(painter, 200, 530, "Последние переводы", 12, 600, 220)
    for index in range(3):
        left = 200 + index * 232
        glass_panel(painter, blurred, QRect(left, 550, 212, 110), 18)
        text(painter, left + 18, 580, "LIVE" if index == 0 else "FILE", 7, 600,
             220 if index == 0 else 150, tracking=12)
        text(painter, left + 18, 608, ["Совещание", "Лекция", "Интервью"][index],
             12, 600)
        text(painter, left + 18, 640, "EN → RU · 7 мин", 9, 400, 160)

    painter.end()
    canvas.save(str(OUT))
    print(f"saved -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
