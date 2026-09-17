"""Hide a window from Zoom, Meet and the rest of the capture stack.

Windows 10 2004 (and 11, which is what this product runs on) lets a top-level
window opt out of screen capture with `SetWindowDisplayAffinity` and
`WDA_EXCLUDEFROMCAPTURE`. DXGI Desktop Duplication honours it, and that is
what Chromium's `getDisplayMedia`, Zoom and Teams use for a full-screen share.

The window stays visible on the presenter's monitor. It simply does not appear
in the frame that gets sent to the call. The older `WDA_MONITOR` flag is not
used: it paints a black rectangle into the capture, which is worse than
leaving the subtitles up.

Sharing a single application window is a different path -- the overlay is not
part of that window, so the flag does not come into it.
"""

from __future__ import annotations

import sys

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def apply(hwnd: int, hidden_from_capture: bool, setter=None) -> bool:
    """Return True when the OS accepted the request.

    Off Windows, or without a real HWND, there is nothing to honour: the
    function reports failure so the caller can say so rather than pretend.
    `setter` is the Windows call, injectable so the flag can be tested
    without a desktop.
    """
    if not hwnd:
        return False
    affinity = WDA_EXCLUDEFROMCAPTURE if hidden_from_capture else WDA_NONE
    try:
        fn = setter or _windows_set
        return bool(fn(hwnd, affinity))
    except (AttributeError, OSError, ValueError, TypeError):
        return False


def _windows_set(hwnd: int, affinity: int) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    setter = ctypes.windll.user32.SetWindowDisplayAffinity
    setter.argtypes = [wintypes.HWND, wintypes.DWORD]
    setter.restype = wintypes.BOOL
    return bool(setter(wintypes.HWND(hwnd), affinity))
