"""Linguaflow desktop interface."""

# QtWebEngine has to be loaded before the QApplication exists; imported any
# later it cannot share the GUI's OpenGL context and the browser screen
# comes up blank. Every entry point imports this package first.
try:
    import PySide6.QtWebEngineWidgets  # noqa: F401
except ImportError:  # a build without the web engine still runs, minus the browser
    pass
