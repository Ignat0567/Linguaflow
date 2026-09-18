"""Day 7: the rough edges a user found by using the thing.

Four reports, each of them a small fault with a real cost: a border that
stopped short, three acronyms with nothing to tell them apart, a job that
started before it was asked to, and a list with no way to reach the files it
described or to clear itself.
"""

from __future__ import annotations

import sys
import tempfile

import pytest

from lt_ui import i18n
from lt_ui.store import HistoryEntry, Store


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUAFLOW_DATA", str(tmp_path / "profile"))
    from lt_core.runtime import bootstrap
    from lt_ui.store import MODEL_ROOT
    from lt_ui.window import Window

    bootstrap(MODEL_ROOT)
    return Window(Store(tmp_path / "state"))


def entry(**over) -> HistoryEntry:
    base = dict(
        id="e1", kind="file", title="лекция.m4a", source_language="en",
        target_language="ru", duration=453.0, created="2026-09-17T12:00:00",
    )
    base.update(over)
    return HistoryEntry(**base)


# -- a job starts when it is asked to -----------------------------------

def test_choosing_a_file_does_not_start_the_job(window):
    """It loads models, runs for minutes and may send lines to a service.
    That is not something to begin because a file was dropped."""
    from lt_ui.screens.upload import _EXAMPLE, _Ready

    window.goto("upload")
    window._upload.open_path(_EXAMPLE)
    assert isinstance(window._upload._stack.currentWidget(), _Ready)
    assert not window._upload._pending


def test_the_chosen_file_is_named_before_starting(window):
    from lt_ui.screens.upload import _EXAMPLE

    window.goto("upload")
    window._upload.open_path(_EXAMPLE)
    assert _EXAMPLE.name in window._upload._ready._name.text()


def test_another_file_goes_back_without_starting(window):
    from lt_ui.screens.upload import _EXAMPLE, _Idle

    window.goto("upload")
    window._upload.open_path(_EXAMPLE)
    window._upload.reset()
    assert isinstance(window._upload._stack.currentWidget(), _Idle)
    assert window._upload._path is None


def test_a_missing_file_still_says_so(window, tmp_path):
    window.goto("upload")
    window._upload.open_path(tmp_path / "absent.mp4")
    assert "absent.mp4" in window._upload._busy._stage.text()


def test_the_language_pair_is_read_from_the_page_in_front(window):
    """Two pages carry a pair. Reading the wrong one threw away a change made
    on the confirmation screen without a sign."""
    from lt_ui.screens.upload import _EXAMPLE

    window.goto("upload")
    window._upload.open_path(_EXAMPLE)
    window._upload._ready.pair.set_pair("de", "ru")
    window._upload._sync_pair()
    assert window.store.settings.to_lang == "ru"
    assert window.store.settings.from_lang == "de"


# -- the history can be reached and cleared -----------------------------

def test_a_row_offers_the_folder_when_there_is_one(window, tmp_path):
    from lt_ui import glass

    folder = tmp_path / "job"
    folder.mkdir()
    window.store.add(entry(folder=str(folder)))
    window.goto("history")
    links = window._history.findChildren(glass.TextLink)
    assert any("папк" in link.text().lower() or "folder" in link.text().lower()
               or "ordner" in link.text().lower() for link in links)


def test_a_row_with_no_folder_offers_nothing_to_open(window):
    """A link that opens nothing is worse than no link."""
    from lt_ui import glass

    window.store.add(entry(folder=""))
    window.goto("history")
    labels = [link.text() for link in window._history.findChildren(glass.TextLink)]
    assert all("Очистить" in text for text in labels)


def test_the_label_matches_what_the_link_does(window, tmp_path):
    """It was called «Скачать» and it opened a folder. A label describing a
    different action is worse than none."""
    from lt_ui import glass

    folder = tmp_path / "job"
    folder.mkdir()
    window.store.add(entry(folder=str(folder)))
    window.goto("history")
    labels = [link.text() for link in window._history.findChildren(glass.TextLink)]
    assert not any("Скачать" in text for text in labels)


def test_clearing_asks_once_first(window):
    window.store.add(entry())
    window.goto("history")
    window._history._on_clear()
    assert len(window.store.entries) == 1
    assert "ещё раз" in window._history._clear.text()


def test_the_second_press_clears_the_list(window):
    window.store.add(entry())
    window.goto("history")
    window._history._on_clear()
    window._history._on_clear()
    assert window.store.entries == []


def test_clearing_the_list_leaves_the_files(window, tmp_path):
    """The entries name folders a user may still want, and a button in a list
    is not where anyone expects gigabytes to be deleted."""
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "result.wav").write_bytes(b"0" * 64)
    window.store.add(entry(folder=str(folder)))
    window.store.clear_history()
    assert (folder / "result.wav").exists()


def test_coming_back_finds_the_confirmation_disarmed(window):
    """Returning to a primed button would be a trap: one press away from
    clearing a list the user came back to look at."""
    window.store.add(entry())
    window.goto("history")
    window._history._on_clear()
    window.goto("home")
    window.goto("history")
    assert "ещё раз" not in window._history._clear.text()
    assert len(window.store.entries) == 1


def test_the_clear_action_hides_when_there_is_nothing_to_clear(window):
    window.goto("history")
    assert not window._history._header.isVisible()


# -- the subtitle formats explain themselves ----------------------------

@pytest.mark.parametrize("value,marker", [
    ("srt", "плееры"), ("vtt", "веб"), ("txt", "без времени"),
])
def test_each_format_says_what_it_is_for(window, value, marker):
    """Three acronyms and no way to choose between them is a guess."""
    i18n.set_language("ru")
    window.store.settings.sub_format = value
    window.goto("settings")
    window._settings._show_format()
    assert marker in window._settings._format_note.text()


def test_the_explanation_follows_the_choice(window):
    i18n.set_language("ru")
    window.goto("settings")
    window._settings._sync_format("txt")
    first = window._settings._format_note.text()
    window._settings._sync_format("srt")
    assert window._settings._format_note.text() != first


# -- the key field has room for its own border --------------------------

def test_the_key_row_is_taller_than_the_field_in_it(window):
    """At exactly the field's height the bottom border is clipped away."""
    from lt_ui.screens.settings import _ROW_HEIGHT

    window.goto("settings")
    field = window._settings._key
    assert window._settings._key_wrap.minimumHeight() > field.height()
    assert _ROW_HEIGHT >= 34
