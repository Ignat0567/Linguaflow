"""Build the application icon from the supplied logotype.

    python tools/make_icon.py

The icon is not drawn here. `assets/wordmark.png` is a designer's logotype,
and the mark on the taskbar should be that same lettering rather than an
approximation of it -- so two of its letters, the L of "Lingua" and the f of
"flow", are cut out of the wordmark itself and set together on a dark tile.
If the logotype is ever replaced, run this again and the icon follows it.

Cutting a letter out of joined-up script takes more than a rectangle: the
strokes run into their neighbours, and a crop brings pieces of them along.
The crop is also what severs those pieces, though -- once the slice is
taken, a neighbour's stub is no longer joined to anything -- so keeping only
the blob the letter itself forms leaves the letter clean. `carve` does that,
and reports how much of the slice it threw away, which is the number to
watch if the logotype changes.

The two letters are then set at the heights they have in the logotype, so
the f still rises above the L and drops below it. Only the gap between them
is the icon's own decision.

Windows asks for the icon at many sizes and picks one per context: 16px in
the title bar, 32px on the taskbar, 256px in the file dialog's large view.
An ornate script capital survives that range only if it is given more of the
tile as it gets smaller, so the padding shrinks with the size instead of
staying proportional.

The `.ico` is assembled here rather than by an image library, because the
format is a header and a list of pictures and because Qt cannot write one.
Sizes up to 48 are stored as bitmaps, which every version of Explorer reads;
the larger ones are PNG, which is what keeps a 256px icon from costing a
quarter of a megabyte.
"""

from __future__ import annotations

import struct
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QByteArray, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter,
)

ROOT = Path(__file__).resolve().parent.parent
WORDMARK = ROOT / "assets" / "wordmark.png"
ICON_ICO = ROOT / "assets" / "icon.ico"
ICON_PNG = ROOT / "assets" / "icon.png"

#: The columns each letter lives in, in the logotype's own coordinates.
#: The script is joined up, so there is no gap to find: these were chosen by
#: cutting a range of slices and looking at what came out whole.
L_COLUMNS = (0, 150)
F_COLUMNS = (556, 608)

#: How far the f sits into the L, as a share of the L's width. Below this
#: the two read as separate letters with a hole between them; much above it
#: the f's stem crosses the L's arm and they smear together.
OVERLAP = 0.18

#: A slice that throws away more than this is a slice in the wrong place --
#: it has taken most of a neighbour, so the letter positions need looking at
#: again rather than quietly shipping a mark with a stub on it.
MOST_A_SLICE_MAY_LOSE = 0.15

#: Alpha below this is the antialiased edge of nothing.
INK = 40

#: The tile: the app's own near-black, lifted at the top so the square does
#: not read as a hole on a dark taskbar.
TOP = QColor("#1b2233")
BOTTOM = QColor("#04060c")

#: Windows uses each of these somewhere.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

#: Below this, the monogram stops being two letters and becomes a smudge:
#: sixteen pixels across cannot hold an L and an f of joined-up script with
#: anything between them. Measured by rendering it -- no gap, more gap, less
#: margin, a flatter tile -- and none of them resolved the two strokes. So
#: the smallest pictures carry the initial alone, which is what the .ico
#: format is for: a different drawing at each size, not one drawing scaled.
#: Everywhere the icon is looked at as a mark -- taskbar, alt-tab, the file
#: dialog -- is 32 or larger and gets both letters.
MONOGRAM_FROM = 24

#: Past this, the picture inside the .ico is a PNG rather than a bitmap.
PNG_FROM = 64


def carve(source: QImage, first: int, last: int) -> tuple[QImage, int, float]:
    """One letter, alone, out of a slice of joined-up script.

    Returns the letter, the row it starts on in the logotype -- so the two
    can be set back at their own heights -- and the share of the slice's ink
    that was discarded as somebody else's stroke.
    """
    slice_ = source.copy(QRect(first, 0, last - first, source.height()))
    width, height = slice_.width(), slice_.height()
    lit = [
        [((slice_.pixel(x, y) >> 24) & 0xFF) > INK for y in range(height)]
        for x in range(width)
    ]

    seen = [[False] * height for _ in range(width)]
    blobs: list[list[tuple[int, int]]] = []
    for x0 in range(width):
        for y0 in range(height):
            if not lit[x0][y0] or seen[x0][y0]:
                continue
            queue, cells = deque([(x0, y0)]), []
            seen[x0][y0] = True
            while queue:
                x, y = queue.popleft()
                cells.append((x, y))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if (0 <= nx < width and 0 <= ny < height
                                and lit[nx][ny] and not seen[nx][ny]):
                            seen[nx][ny] = True
                            queue.append((nx, ny))
            blobs.append(cells)

    if not blobs:
        raise SystemExit(f"{WORDMARK} has no ink in columns {first}..{last}")

    blobs.sort(key=len, reverse=True)
    letter = blobs[0]
    dropped = 1 - len(letter) / sum(len(blob) for blob in blobs)

    out = QImage(width, height, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    for x, y in letter:
        out.setPixel(x, y, source.pixel(first + x, y))

    xs = [cell[0] for cell in letter]
    ys = [cell[1] for cell in letter]
    box = QRect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
    return out.copy(box), min(ys), dropped


def monogram(left: QImage, left_top: int, right: QImage, right_top: int) -> QImage:
    """The two letters as one mark, each at its logotype height."""
    offset = int(left.width() * (1 - OVERLAP))
    lift = right_top - left_top
    top = min(0, lift)
    canvas = QImage(
        max(left.width(), offset + right.width()),
        max(left.height(), lift + right.height()) - top,
        QImage.Format_ARGB32,
    )
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.drawImage(0, -top, left)
    painter.drawImage(offset, lift - top, right)
    painter.end()
    return canvas


def padding_for(size: int) -> float:
    """How much of the tile is margin, as a fraction of its side.

    A 256px tile can afford air around the letter. A 16px one cannot: at that
    size the margin is most of the icon, and what is left is a smudge.
    """
    if size <= 24:
        return 0.06
    if size <= 48:
        return 0.10
    return 0.15


def tile(size: int, glyph: QImage) -> QImage:
    out = QImage(size, size, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    gradient = QLinearGradient(0, 0, 0, size)
    gradient.setColorAt(0.0, TOP)
    gradient.setColorAt(1.0, BOTTOM)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(gradient))
    radius = size * 0.22
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    room = size * (1 - padding_for(size) * 2)
    scale = min(room / glyph.width(), room / glyph.height())
    width, height = glyph.width() * scale, glyph.height() * scale
    painter.drawImage(
        QRectF((size - width) / 2, (size - height) / 2, width, height), glyph
    )
    painter.end()
    return out


def as_png(image: QImage) -> bytes:
    # The byte array is held in a name of its own: handed straight to QBuffer
    # as a temporary, it is collected while the buffer still points at it.
    store = QByteArray()
    buffer = QBuffer(store)
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(store)


def as_bitmap(image: QImage) -> bytes:
    """One picture in the .ico's own bitmap form.

    A 32-bit DIB whose declared height is doubled: the format dates from
    before alpha, so it still expects a second, one-bit mask underneath. The
    alpha channel is what actually gets used, so the mask is all zeros.
    """
    size = image.width()
    rgba = image.convertToFormat(QImage.Format_ARGB32)

    header = struct.pack(
        "<IiiHHIIiiII",
        40,             # this header's size
        size,           # width
        size * 2,       # height: the colours and the mask, stacked
        1,              # planes
        32,             # bits per pixel
        0,              # no compression
        0,              # image size, which may be left at zero
        0, 0, 0, 0,     # resolution and palette, none of which apply
    )

    rows = []
    for y in range(size - 1, -1, -1):        # bottom-up, as the format wants
        row = bytearray()
        for x in range(size):
            pixel = rgba.pixel(x, y)
            row += bytes((pixel & 0xFF,            # blue
                          (pixel >> 8) & 0xFF,     # green
                          (pixel >> 16) & 0xFF,    # red
                          (pixel >> 24) & 0xFF))   # alpha
        rows.append(bytes(row))

    mask_stride = ((size + 31) // 32) * 4
    mask = bytes(mask_stride * size)
    return header + b"".join(rows) + mask


def write_ico(pictures: list[tuple[int, bytes]], target: Path) -> None:
    count = len(pictures)
    offset = 6 + 16 * count
    directory, payload = bytearray(), bytearray()
    for size, blob in pictures:
        directory += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0, 0, 1, 32,
            len(blob), offset,
        )
        payload += blob
        offset += len(blob)
    target.write_bytes(
        struct.pack("<HHH", 0, 1, count) + bytes(directory) + bytes(payload)
    )


def main() -> int:
    # Held in a name: a QGuiApplication that is only constructed is collected
    # again, and the first QImage after that takes the process with it.
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    assert app is not None
    if not WORDMARK.is_file():
        raise SystemExit(f"no logotype at {WORDMARK}")

    wordmark = QImage(str(WORDMARK))
    if wordmark.isNull():
        raise SystemExit(f"{WORDMARK} could not be read")

    ell, ell_top, ell_lost = carve(wordmark, *L_COLUMNS)
    eff, eff_top, eff_lost = carve(wordmark, *F_COLUMNS)
    for name, letter, lost in (("L", ell, ell_lost), ("f", eff, eff_lost)):
        print(f"  {name}: {letter.width()}x{letter.height()}, "
              f"{lost:.0%} of the slice discarded as a neighbour")
        if lost > MOST_A_SLICE_MAY_LOSE:
            raise SystemExit(
                f"the slice for {name} is mostly somebody else's letter -- "
                f"check the column ranges against the logotype"
            )

    both = monogram(ell, ell_top, eff, eff_top)
    print(f"monogram: {both.width()}x{both.height()}")

    pictures = []
    for size in SIZES:
        glyph = both if size >= MONOGRAM_FROM else ell
        image = tile(size, glyph)
        blob = as_png(image) if size >= PNG_FROM else as_bitmap(image)
        pictures.append((size, blob))
        kind = "png" if size >= PNG_FROM else "bmp"
        drawn = "Lf" if size >= MONOGRAM_FROM else "L"
        print(f"  {size:>3}px  {kind}  {drawn:>2}  {len(blob):>7} bytes")

    write_ico(pictures, ICON_ICO)
    tile(256, glyph).save(str(ICON_PNG), "PNG")
    print(f"wrote {ICON_ICO} ({ICON_ICO.stat().st_size} bytes)")
    print(f"wrote {ICON_PNG} ({ICON_PNG.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
