"""Linguaflow desktop interface."""

import os

# QtWebEngine 6.11.2 on Windows crashes (access violation in
# Qt6WebEngineCore.dll) when a view playing a video is hidden and shown again
# -- switching away from the Browser screen and back. Measured on a bare
# QWebEngineView with nothing of ours in it: every run fell within 36-57 s of
# switching every 1.5 s, first freezing for several seconds. With GPU
# compositing off it ran 100 s and more; the page still decodes video on the
# GPU and cost 20 % of a core against 16 % before (the ANGLE backends that
# also avoided it cost two cores). Chromium reads its flags once, at start.
_FLAG = "--disable-gpu-compositing"
_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
if _FLAG not in _flags.split():
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{_flags} {_FLAG}".strip()

# QtWebEngine has to be loaded before the QApplication exists; imported any
# later it cannot share the GUI's OpenGL context and the browser screen
# comes up blank. Every entry point imports this package first.
try:
    import PySide6.QtWebEngineWidgets  # noqa: F401
except ImportError:  # a build without the web engine still runs, minus the browser
    pass
