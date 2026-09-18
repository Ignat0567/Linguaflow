"""The handoff's design tokens, in Qt terms, in two modes.

The handoff is written in CSS: rgba fills, backdrop-filter, a type scale in
pixels. Qt has none of those names, so every value is translated once, here,
and nothing downstream reaches for a literal colour.

It is also written dark-only -- white text on a photograph under a near-black
scrim. A light mode is therefore not a switch but a second set of values, and
the thing that makes it possible is that the glass itself does not invert:
frosted white over a bright photograph is still glass. What inverts is the
scrim, which becomes a pale veil, and the text, which becomes near-black.

Because of that, the surface colour and the foreground colour -- both plain
white in dark mode -- are asked for separately: `surface()` and `ink()`. They
were one call before the light mode existed, and that is exactly the kind of
shortcut that makes a second theme impossible later.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QLabel, QWidget

DARK, LIGHT = "dark", "light"

#: Which mode the app is painting in. Changed through `set_mode`.
MODE = DARK

#: Page base, seen only where the photograph does not reach.
BASE_DARK = QColor("#04060c")
BASE_LIGHT = QColor("#eef1f8")
#: Text on a filled accent surface, and the foreground in light mode.
INK = QColor("#0d0f1a")

#: The one tweakable colour. Drives active nav, the primary card, the record
#: button, progress and every "on" state.
ACCENT = QColor("#7fa4ff")
ACCENT_ALTERNATES = ("#7fa4ff", "#b98cff", "#5ee6c9", "#ff9d7a")


def set_mode(mode: str) -> None:
    global MODE
    MODE = LIGHT if mode == LIGHT else DARK


def is_light() -> bool:
    return MODE == LIGHT


def base() -> QColor:
    return BASE_LIGHT if is_light() else BASE_DARK


def white(alpha: float) -> QColor:
    """Literal white at a given opacity."""
    colour = QColor(255, 255, 255)
    colour.setAlphaF(max(0.0, min(1.0, alpha)))
    return colour


def ink(alpha: float) -> QColor:
    """Foreground: white on the dark theme, near-black on the light one."""
    colour = QColor(INK) if is_light() else QColor(255, 255, 255)
    colour.setAlphaF(max(0.0, min(1.0, alpha)))
    return colour


def surface(alpha: float) -> QColor:
    """The glass fill. White in both modes -- frosted glass is frosted."""
    return white(alpha)


def accent(alpha: float = 1.0) -> QColor:
    colour = QColor(ACCENT)
    colour.setAlphaF(max(0.0, min(1.0, alpha)))
    return colour


def set_accent(value: str) -> None:
    """Change the accent for the whole app; screens repaint from it."""
    global ACCENT
    ACCENT = QColor(value)


def on_accent() -> QColor:
    """Text placed on a filled accent surface.

    Near-black in both modes: the accents are all light enough that white
    text on them fails to read, which is why this is not simply `ink()`.
    """
    return QColor(INK)


#: Polished gold, as a vertical ramp rather than a colour.
#:
#: A single gold is paint; what reads as metal is the ramp -- a dark base, a
#: bright band where the light catches, a shadowed middle, and a second
#: highlight lower down. Flat colour cannot do it at any value, which is why
#: this is a list of stops and not a swatch.
GOLD_RAMP: tuple[tuple[float, str], ...] = (
    (0.00, "#6E4410"),
    (0.16, "#B9862A"),
    (0.34, "#FFF3BE"),
    (0.46, "#F0CC63"),
    (0.60, "#A9741B"),
    (0.78, "#E9C879"),
    (1.00, "#5E3A0C"),
)

#: The light theme deepens the same metal rather than changing it: the bright
#: band that reads as a highlight over a dark photograph becomes a hole over a
#: pale one, so every stop is taken down.
GOLD_RAMP_LIGHT: tuple[tuple[float, str], ...] = (
    (0.00, "#4A2C08"),
    (0.16, "#8A5F17"),
    (0.34, "#E8C878"),
    (0.46, "#C79A33"),
    (0.60, "#7A5210"),
    (0.78, "#BE9034"),
    (1.00, "#3E2406"),
)

#: The extruded side of the letters, and the line around them.
GOLD_EDGE = QColor("#3B2408")


def gold_ramp() -> tuple[tuple[float, str], ...]:
    return GOLD_RAMP_LIGHT if is_light() else GOLD_RAMP


def gold() -> QColor:
    """One representative stop, for anything that cannot take a gradient."""
    return QColor(gold_ramp()[3][1])


# -- hierarchy of foreground text ---------------------------------------
PRIMARY = 1.00
SECONDARY = 0.75
TERTIARY = 0.60
MUTED = 0.40

#: Light text at 75% on a photograph reads; dark text at 75% on a pale veil
#: looks faded, so the light mode leans harder on every step below primary.
_LIGHT_LIFT = 0.12


def text_alpha(alpha: float) -> float:
    """The opacity a given step in the hierarchy needs in the current mode."""
    if not is_light() or alpha >= PRIMARY:
        return alpha
    return min(1.0, alpha + _LIGHT_LIFT)


# -- surfaces ------------------------------------------------------------
#: Glass tint in dark mode: the rgba(255,255,255,0.07-0.10) of the recipe.
TINT_DARK, TINT_DARK_RAISED = 0.085, 0.13
#: In light mode the same panels need far more white to separate from a bright
#: photograph -- at 8% they read as a smudge rather than a surface.
TINT_LIGHT, TINT_LIGHT_RAISED = 0.55, 0.68

#: What a hover adds, per the handoff's suggested +4% white.
HOVER_LIFT = 0.04


def tint(raised: bool = False) -> float:
    if is_light():
        return TINT_LIGHT_RAISED if raised else TINT_LIGHT
    return TINT_DARK_RAISED if raised else TINT_DARK


def border() -> float:
    """Hairline edge opacity. Dark mode edges in white, light mode in ink."""
    return 0.10 if is_light() else 0.19


def border_colour() -> QColor:
    return ink(border()) if is_light() else white(border())


def highlight() -> float:
    """The inset top edge that makes a panel read as glass rather than fog."""
    return 0.75 if is_light() else 0.30


#: Kept for anything still reading the dark values directly.
TINT = TINT_DARK
TINT_RAISED = TINT_DARK_RAISED
BORDER = 0.19
HIGHLIGHT = 0.30

# -- the scrim over the photograph --------------------------------------
#: Three stops, top to bottom, as the handoff specifies them.
SCRIM_DARK = ((4, 6, 14), (0.55, 0.72, 0.88))
#: A pale veil rather than a dark one. Heavier than the dark scrim, because
#: near-black text needs more of the photograph taken out from under it than
#: white text does.
SCRIM_LIGHT = ((243, 245, 251), (0.66, 0.78, 0.90))


def scrim() -> tuple[tuple[int, int, int], tuple[float, float, float]]:
    return SCRIM_LIGHT if is_light() else SCRIM_DARK


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


# -- repainting after a mode change -------------------------------------
#: Labels colour themselves through a style sheet rather than a paintEvent,
#: and a style sheet does not change when the widget is merely updated. Each
#: one remembers which step of the hierarchy it belongs to so the colour can
#: be recomputed instead of guessed.
ALPHA_PROPERTY = "lf_text_alpha"


def label_colour(alpha: float) -> str:
    colour = ink(text_alpha(alpha))
    return (
        f"color: rgba({colour.red()},{colour.green()},{colour.blue()},"
        f"{colour.alphaF():.3f}); background: transparent;"
    )


def restyle(root: QWidget) -> None:
    """Re-apply text colours under `root` after the mode changed."""
    from .glass import GlassInput, GlassSelect

    for kind in (GlassSelect, GlassInput):
        for widget in root.findChildren(kind):
            widget.setStyleSheet(kind.style_for_mode())
    for widget in root.findChildren(QLabel):
        alpha = widget.property(ALPHA_PROPERTY)
        if alpha is not None:
            widget.setStyleSheet(label_colour(float(alpha)))
    root.update()
    for widget in root.findChildren(QWidget):
        widget.update()
