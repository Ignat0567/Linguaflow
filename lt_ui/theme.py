"""The handoff's design tokens, in Qt terms.

The handoff is written in CSS: rgba fills, backdrop-filter, a type scale in
pixels. Qt has none of those names, so every value is translated once, here,
and nothing downstream reaches for a literal colour.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont

#: Page base, seen only where the photograph does not reach.
BASE = QColor("#04060c")
#: Text on a filled accent surface, and the background of a dropdown.
INK = QColor("#0d0f1a")

#: The one tweakable colour. Drives active nav, the primary card, the record
#: button, progress and every "on" state.
ACCENT = QColor("#7fa4ff")
ACCENT_ALTERNATES = ("#7fa4ff", "#b98cff", "#5ee6c9", "#ff9d7a")


def white(alpha: float) -> QColor:
    """White at a given opacity -- the handoff's whole foreground palette."""
    colour = QColor(255, 255, 255)
    colour.setAlphaF(max(0.0, min(1.0, alpha)))
    return colour


def accent(alpha: float = 1.0) -> QColor:
    colour = QColor(ACCENT)
    colour.setAlphaF(max(0.0, min(1.0, alpha)))
    return colour


def set_accent(value: str) -> None:
    """Change the accent for the whole app; screens repaint from it."""
    global ACCENT
    ACCENT = QColor(value)


# -- hierarchy of foreground text ---------------------------------------
PRIMARY = 1.00
SECONDARY = 0.75
TERTIARY = 0.60
MUTED = 0.40

# -- surfaces ------------------------------------------------------------
#: Glass tint, the rgba(255,255,255,0.07-0.10) of the recipe.
TINT = 0.085
TINT_RAISED = 0.13
BORDER = 0.19
#: The inset top highlight that makes a panel read as glass rather than fog.
HIGHLIGHT = 0.30

# -- geometry ------------------------------------------------------------
RADIUS_PILL = 999
RADIUS_PANEL = 24
RADIUS_CARD = 20
RADIUS_ROW = 18

GUTTER = 28
NAV_HEIGHT = 44
CONTENT_WIDTH = 1080

#: Blur radius of the backdrop, per the recipe's 20-28px.
BLUR = 24
SATURATION = 1.7

FAMILY = "Segoe UI"


def font(size: int, weight: int = 400, tracking: float = 0.0) -> QFont:
    """A font from the handoff's scale.

    `size` is the CSS pixel size; Qt is told pixels directly rather than points
    so the numbers in the handoff can be used as written.
    """
    value = QFont(FAMILY)
    value.setPixelSize(size)
    value.setWeight(QFont.Weight(weight))
    if tracking:
        value.setLetterSpacing(QFont.PercentageSpacing, 100 + tracking)
    return value


def eyebrow_font() -> QFont:
    """The small uppercase label: 11px, wide tracking."""
    return font(11, 600, tracking=10)
