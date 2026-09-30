"""What the program does when something goes wrong inside it.

A user reported that Linguaflow "just closed" when they changed the
interface language. The Windows crash dump said the process had called
abort() from Qt's own code, on the main thread, inside the window procedure
that was delivering a mouse click -- the shape a Python exception makes when
it escapes a Qt slot. Nothing was written down anywhere, so the cause had to
be read out of a 336 MB dump.

Two things follow, and both are tested here: the program records why it
died, and it stops destroying the widget tree from inside the click that
asked for the change.
"""

from __future__ import annotations

import sys
import threading

import pytest

from lt_ui import crashlog


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUAFLOW_DATA", str(tmp_path / "profile"))
    from lt_core.runtime import bootstrap
    from lt_ui.store import MODEL_ROOT, Store
    from lt_ui.window import Window

    bootstrap(MODEL_ROOT)
    return Window(Store(tmp_path / "state"))


@pytest.fixture(autouse=True)
def _forget_installation():
    """`install` is once-only by design; let each test have its own go."""
    before = (sys.excepthook, threading.excepthook, sys.unraisablehook)
    crashlog._installed = False
    yield
    sys.excepthook, threading.excepthook, sys.unraisablehook = before
    crashlog._installed = False


# -- the record ---------------------------------------------------------

def test_a_crash_is_written_where_the_settings_are(tmp_path):
    written = crashlog.record("something went wrong", tmp_path / "profile")
    assert written is not None and written.exists()
    assert written.name == crashlog.LOG_NAME
    assert "something went wrong" in written.read_text(encoding="utf-8")


def test_the_record_says_when(tmp_path):
    written = crashlog.record("boom", tmp_path)
    text = written.read_text(encoding="utf-8")
    assert "=====" in text
    # A date, so two reports a week apart can be told apart.
    assert text.count("-") >= 2


def test_a_second_crash_is_added_not_replaced(tmp_path):
    crashlog.record("first", tmp_path)
    written = crashlog.record("second", tmp_path)
    text = written.read_text(encoding="utf-8")
    assert "first" in text and "second" in text


def test_the_log_does_not_grow_without_end(tmp_path):
    target = crashlog.log_path(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x" * (crashlog.MAX_BYTES + 10), encoding="utf-8")
    crashlog.record("after the cap", tmp_path)
    text = target.read_text(encoding="utf-8")
    assert "after the cap" in text
    assert len(text) < crashlog.MAX_BYTES


def test_a_log_that_cannot_be_written_is_not_a_second_failure(tmp_path):
    """Recording must never be the thing that takes the program down."""
    blocked = tmp_path / "wall"
    blocked.write_text("I am a file, not a folder", encoding="utf-8")
    assert crashlog.record("nowhere to go", blocked) is None


# -- the hooks ----------------------------------------------------------

def test_an_unhandled_exception_is_recorded(tmp_path):
    seen = []
    original = sys.excepthook
    sys.excepthook = lambda *a: seen.append(a)
    try:
        crashlog.install(tmp_path)
        try:
            raise ValueError("the thing that actually broke")
        except ValueError:
            sys.excepthook(*sys.exc_info())
    finally:
        sys.excepthook = original

    text = crashlog.log_path(tmp_path).read_text(encoding="utf-8")
    assert "the thing that actually broke" in text
    assert "ValueError" in text
    assert "Traceback" in text
    assert seen, "the hook that was there before must still be called"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_an_exception_that_ends_a_thread_is_recorded(tmp_path):
    """The thread is meant to die here; that is what is being recorded."""
    crashlog.install(tmp_path)

    def explode():
        raise RuntimeError("a worker died quietly")

    worker = threading.Thread(target=explode, name="Doomed")
    worker.start()
    worker.join()

    text = crashlog.log_path(tmp_path).read_text(encoding="utf-8")
    assert "a worker died quietly" in text
    assert "Doomed" in text


def test_installing_twice_does_not_stack_hooks(tmp_path):
    crashlog.install(tmp_path)
    once = sys.excepthook
    crashlog.install(tmp_path)
    assert sys.excepthook is once


# -- the language change ------------------------------------------------

def test_the_language_change_waits_for_the_click_to_finish(window):
    """The chip being clicked lives inside the tree the change destroys.

    Tearing it down inside its own signal -- while Qt is still dispatching
    the mouse message -- is what the crash dump caught. The rebuild has to
    wait one turn of the event loop.
    """
    from PySide6.QtCore import QCoreApplication

    window.goto("settings")
    before = window._shell
    chips = window._settings._ui_language
    chips._group.button(chips._keys.index("en")).click()

    assert window._shell is before, (
        "the shell was rebuilt inside the click handler -- the widget that "
        "reported the change was deleted while Qt was still using it"
    )
    assert window.store.settings.ui_language == "en", "the choice is saved at once"

    QCoreApplication.processEvents()
    assert window._shell is not before, "the rebuild still has to happen"


def test_the_language_really_changes(window):
    from PySide6.QtCore import QCoreApplication
    from lt_ui import i18n

    window.goto("settings")
    chips = window._settings._ui_language
    chips._group.button(chips._keys.index("de")).click()
    QCoreApplication.processEvents()

    assert i18n.LANGUAGE == "de"
    assert window.current_screen == "settings", "the open screen is kept"


def test_the_deferred_rebuild_is_held_by_the_window(window):
    """The window outlives the rebuild; the settings screen does not.

    If the call were held by the screen instead, the timer would fire into
    something already deleted -- the bug this fix exists to avoid.
    """
    import inspect

    from lt_ui.screens import settings as settings_module

    source = inspect.getsource(settings_module.SettingsScreen._sync_ui_language)
    assert "singleShot" in source, "the rebuild must not run inside the click"
    assert "self.app.apply_language" in source, (
        "the deferred call must belong to the window, not to the screen "
        "that the rebuild destroys"
    )


def test_the_program_starts_recording_before_it_shows_anything(
    app, tmp_path, monkeypatch
):
    """A crash during the first seconds is the one hardest to report."""
    from PySide6.QtWidgets import QApplication

    from lt_ui import window as window_module

    monkeypatch.setenv("LINGUAFLOW_DATA", str(tmp_path / "profile"))
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.setattr(window_module.Window, "show", lambda self: None)

    asked: list = []
    monkeypatch.setattr(window_module.crashlog, "install", lambda folder: asked.append(folder))

    window_module.run(data_dir=str(tmp_path / "state"))
    assert asked, "the program must install the recorder on the way up"
    assert str(asked[0]).endswith("state"), "the log belongs with the user's profile"


# -- timers that outlive their screen -----------------------------------

def test_the_browser_caption_timer_belongs_to_its_screen(window):
    """A loose singleShot cannot be cancelled when its screen is destroyed.

    The language change builds every screen again, so a timer with no owner
    would fire into a page that no longer exists.
    """
    browser = window._browser
    assert browser._recaption.parent() is browser
    assert browser._recaption.isSingleShot()

    browser._recaption.start()
    assert browser._recaption.isActive()
    browser.shutdown()
    assert not browser._recaption.isActive(), "shutdown has to stop it"


def test_hiding_captions_again_survives_a_page_that_went_away(window):
    browser = window._browser
    browser._mine = True
    browser._page = None
    browser._hide_captions_again()   # must not raise
