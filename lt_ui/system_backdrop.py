"""Asking the window manager to blur whatever is behind the window.

The app paints its own photograph and then lets the desktop through it, which
without this is the desktop exactly as it is -- text, icons, other windows --
showing through the interface and competing with it. Windows will do the blur
in the compositor, for nothing: the same frosted sheet the taskbar sits on.

Two ways of asking exist and only one of them works here.

`DWMWA_SYSTEMBACKDROP_TYPE`, the documented Windows 11 attribute, is accepted
-- it returns success -- and then does nothing a camera can see: measured
against a sheet of strong colour behind the window, the window came back
flat, with no trace of what was behind it either sharp or blurred. It fills
behind the window's own surface, and this window has one.

`SetWindowCompositionAttribute` with an accent policy is undocumented and is
what actually blurs. It has been in Windows since 10 and is what most of the
applications with a frosted window use.

Nothing here is required for the app to work. Every call is a request, every
failure is silent, and anywhere that is not Windows the interface is simply
unblurred.
"""

from __future__ import annotations

import sys

#: Set the accent policy on a window.
_WCA_ACCENT_POLICY = 19

#: Blur what is behind, with a tint over it. The plainer blur (3) has no tint
#: and lets a bright desktop through hard enough to read the interface over.
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

#: The tint laid over the blur, as Windows wants it: 0xAABBGGRR. A dark, light
#: alpha -- the app paints its own photograph on top and this is only what
#: stops a white desktop glaring through it.
_TINT = 0x40201A10


def blur_behind(widget) -> bool:
    """Frost whatever is behind this window. True if the request was taken."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        handle = int(widget.winId())
        if not handle:
            return False

        class AccentPolicy(ctypes.Structure):
            _fields_ = [
                ("state", ctypes.c_int),
                ("flags", ctypes.c_int),
                ("gradient", ctypes.c_uint),
                ("animation", ctypes.c_int),
            ]

        class Attribute(ctypes.Structure):
            _fields_ = [
                ("attribute", ctypes.c_int),
                ("data", ctypes.POINTER(AccentPolicy)),
                ("size", ctypes.c_size_t),
            ]

        # Flag 2 asks for the blur to cover the whole window rather than only
        # its client area.
        policy = AccentPolicy(_ACCENT_ENABLE_ACRYLICBLURBEHIND, 2, _TINT, 0)
        payload = Attribute(_WCA_ACCENT_POLICY, ctypes.pointer(policy),
                            ctypes.sizeof(policy))
        setter = ctypes.windll.user32.SetWindowCompositionAttribute
        setter.argtypes = [wintypes.HWND, ctypes.POINTER(Attribute)]
        setter.restype = ctypes.c_int
        return bool(setter(wintypes.HWND(handle), ctypes.byref(payload)))
    except Exception:  # noqa: BLE001 -- a backdrop is not worth an error
        return False
