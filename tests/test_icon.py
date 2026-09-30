"""The mark on the title bar and on the taskbar.

The program had no icon of its own, so Windows showed the interpreter's:
a Python logo in the corner of the window and another on the taskbar, with
Linguaflow's windows filed under Python's button. Both are fixed by the same
two things -- an icon, and an application identity to hang it on.

The icon is not drawn by hand. It is cut from `assets/wordmark.png`, the
supplied logotype, by `tools/make_icon.py`, so it stays the same lettering
the program shows above its nav bar.
"""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


# -- the file ------------------------------------------------------------

def test_the_icon_ships_with_the_program():
    from lt_ui.window import APP_ICON

    assert APP_ICON.is_file(), (
        f"{APP_ICON} is missing -- run tools/make_icon.py"
    )


def test_the_icon_holds_every_size_windows_asks_for(app):
    """16 in the title bar, 32 on the taskbar, 256 in a file dialog.

    One picture scaled down is a smudge at 16px; each size is drawn at the
    size it will be shown.
    """
    from lt_ui.window import brand_icon

    icon = brand_icon()
    assert not icon.isNull()
    have = {size.width() for size in icon.availableSizes()}
    for wanted in (16, 24, 32, 48, 256):
        assert wanted in have, f"no {wanted}px picture in the icon"


def test_the_smallest_sizes_are_not_empty(app):
    """A 16px tile that came out blank would pass every other check."""
    from lt_ui.window import brand_icon

    icon = brand_icon()
    for size in (16, 32):
        image = icon.pixmap(size, size).toImage()
        assert not image.isNull()
        lit = sum(
            1
            for x in range(image.width())
            for y in range(image.height())
            if ((image.pixel(x, y) >> 24) & 0xFF) > 20
        )
        assert lit > (size * size) * 0.4, f"the {size}px picture is mostly empty"


def test_the_smallest_pictures_are_drawn_for_their_size(app):
    """Not one drawing scaled down -- that is what makes a 16px smudge.

    The mark is two letters of joined-up script. At 24px and up both fit;
    at 16 and 20 they merge, so those carry the initial alone. If the icon
    ever goes back to a single drawing for every size, this notices.
    """
    from PySide6.QtCore import Qt

    from lt_ui.window import brand_icon

    icon = brand_icon()
    small = icon.pixmap(16, 16).toImage().convertToFormat(
        icon.pixmap(16, 16).toImage().format()
    )
    shrunk = icon.pixmap(48, 48).toImage().scaled(
        16, 16, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
    )

    differing = sum(
        1
        for x in range(16)
        for y in range(16)
        if small.pixel(x, y) != shrunk.pixel(x, y)
    )
    assert differing > 16 * 16 * 0.2, (
        "the 16px picture looks like the large one scaled down -- it should "
        "be drawn for its own size"
    )


def test_a_missing_icon_costs_the_picture_and_not_the_program(app, monkeypatch):
    from pathlib import Path

    from lt_ui import window as window_module

    monkeypatch.setattr(window_module, "APP_ICON", Path("nowhere.ico"))
    assert window_module.brand_icon().isNull()


# -- the wiring ----------------------------------------------------------

def test_the_window_wears_the_icon(app, tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUAFLOW_DATA", str(tmp_path / "profile"))
    from lt_core.runtime import bootstrap
    from lt_ui.store import MODEL_ROOT, Store
    from lt_ui.window import Window

    bootstrap(MODEL_ROOT)
    window = Window(Store(tmp_path / "state"))
    assert not window.windowIcon().isNull()


def test_starting_up_sets_the_icon_and_claims_an_identity(
    app, tmp_path, monkeypatch
):
    """Both, and the identity before the first window is made.

    Windows reads the identity when a window first appears; setting it
    afterwards leaves the taskbar button where it was.
    """
    from PySide6.QtWidgets import QApplication

    from lt_ui import window as window_module

    monkeypatch.setenv("LINGUAFLOW_DATA", str(tmp_path / "profile"))
    order: list[str] = []

    monkeypatch.setattr(
        window_module, "_claim_taskbar_identity",
        lambda: order.append("identity"),
    )
    monkeypatch.setattr(
        QApplication, "setWindowIcon",
        lambda self, icon: order.append("icon"),
    )
    monkeypatch.setattr(window_module.Window, "show", lambda self: order.append("window"))
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)

    window_module.run(data_dir=str(tmp_path / "state"))

    assert "identity" in order and "icon" in order
    assert order.index("identity") < order.index("window")
    assert order.index("icon") < order.index("window")


def test_the_identity_is_ours_and_not_the_interpreter_s():
    from lt_ui.window import APP_ID

    assert "Linguaflow" in APP_ID
    assert "python" not in APP_ID.lower()


def test_claiming_the_identity_never_raises():
    from lt_ui.window import _claim_taskbar_identity

    _claim_taskbar_identity()   # twice, to be sure it is not once-only
    _claim_taskbar_identity()
