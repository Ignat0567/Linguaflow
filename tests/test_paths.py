"""Day 7: where a user's data lives once the program is installed.

`Program Files` is not writable, and one folder of settings shared by everyone
who signs in to a machine is the wrong shape for something holding a person's
languages, their history and their API key.
"""

from __future__ import annotations

import json
import sys

import pytest

from lt_ui.keys import KeyStore
from lt_ui.paths import (
    APP_NAME,
    STATE_FILES,
    legacy_data_dir,
    migrate,
    resolve_data_dir,
    user_data_dir,
)
from lt_ui.store import MODEL_ROOT, ROOT, Store


@pytest.fixture(autouse=True)
def no_override(monkeypatch):
    monkeypatch.delenv("LINGUAFLOW_DATA", raising=False)


# -- where ---------------------------------------------------------------

def test_the_folder_is_per_user_and_named_for_the_app():
    folder = user_data_dir()
    assert folder.name == APP_NAME
    assert str(folder) != str(ROOT)


@pytest.mark.skipif(sys.platform != "win32", reason="проверка для Windows")
def test_on_windows_it_is_the_roaming_profile(monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\Users\someone\AppData\Roaming")
    assert user_data_dir() == __import__("pathlib").Path(
        r"C:\Users\someone\AppData\Roaming"
    ) / APP_NAME


def test_an_override_wins_for_a_portable_copy(monkeypatch, tmp_path):
    """A memory stick, or a test that must not touch a real profile."""
    monkeypatch.setenv("LINGUAFLOW_DATA", str(tmp_path / "portable"))
    assert user_data_dir() == tmp_path / "portable"


def test_models_stay_with_the_installation():
    """Gigabytes, identical for everyone, read-only in use: copying them into
    each profile would be waste, not tidiness."""
    assert MODEL_ROOT.parent == ROOT
    assert str(MODEL_ROOT) not in str(user_data_dir())


# -- carrying the old state across --------------------------------------

def old_folder(tmp_path):
    folder = legacy_data_dir(tmp_path)
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text('{"from_lang": "de"}', encoding="utf-8")
    (folder / "history.json").write_text('[{"id": "abc"}]', encoding="utf-8")
    KeyStore(folder).set("nvidia", "nvapi-carried-across")
    jobs = folder / "jobs" / "abc"
    jobs.mkdir(parents=True)
    (jobs / "result.wav").write_bytes(b"0" * 2048)
    return folder


def test_state_is_carried_to_the_new_place(tmp_path):
    source = old_folder(tmp_path)
    destination = tmp_path / "profile"
    carried = migrate(source, destination)
    assert sorted(carried) == sorted(STATE_FILES)
    assert json.loads((destination / "settings.json").read_text(encoding="utf-8"))


def test_the_key_still_opens_after_being_carried(tmp_path):
    source = old_folder(tmp_path)
    destination = tmp_path / "profile"
    migrate(source, destination)
    assert KeyStore(destination).get("nvidia") == "nvapi-carried-across"


def test_finished_files_are_left_where_they_are(tmp_path):
    """The history names them by absolute path, so they keep working -- and
    moving gigabytes of audio is a poor way to spend a first start."""
    source = old_folder(tmp_path)
    destination = tmp_path / "profile"
    migrate(source, destination)
    assert not (destination / "jobs").exists()
    assert (source / "jobs" / "abc" / "result.wav").exists()


def test_the_old_folder_is_not_emptied(tmp_path):
    """A migration that goes wrong must leave the user where they were."""
    source = old_folder(tmp_path)
    migrate(source, tmp_path / "profile")
    for name in STATE_FILES:
        assert (source / name).exists(), name


def test_migrating_twice_does_not_overwrite_newer_state(tmp_path):
    source = old_folder(tmp_path)
    destination = tmp_path / "profile"
    migrate(source, destination)
    (destination / "settings.json").write_text('{"from_lang": "ru"}',
                                               encoding="utf-8")
    assert migrate(source, destination) == []
    assert "ru" in (destination / "settings.json").read_text(encoding="utf-8")


def test_nothing_to_carry_is_not_an_error(tmp_path):
    assert migrate(tmp_path / "absent", tmp_path / "profile") == []


def test_a_folder_that_is_already_the_destination_is_left_alone(tmp_path):
    folder = old_folder(tmp_path)
    assert migrate(folder, folder) == []


# -- what the store does with it ----------------------------------------

def test_an_explicit_folder_is_used_as_given(tmp_path):
    """Tests and portable copies say where; nothing is migrated behind them."""
    assert resolve_data_dir(tmp_path, tmp_path / "chosen") == tmp_path / "chosen"


def test_the_store_lands_in_the_per_user_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("LINGUAFLOW_DATA", str(tmp_path / "profile"))
    store = Store()
    assert store.root == tmp_path / "profile"
    assert store.keys.path.parent == store.root


def test_the_store_still_honours_an_explicit_folder(tmp_path):
    store = Store(tmp_path / "elsewhere")
    assert store.root == tmp_path / "elsewhere"


# -- when the system moves the folder behind us --------------------------

def test_a_plain_folder_reports_itself(tmp_path):
    from lt_ui.paths import actual_location

    folder = tmp_path / "profile"
    folder.mkdir()
    real, redirected = actual_location(folder)
    assert real == folder.resolve()
    assert not redirected


def test_a_redirected_folder_is_reported_as_such(tmp_path):
    """Store-installed Python redirects %APPDATA% into a package sandbox, so
    the program names a path that File Explorer says does not exist. Measured
    on this machine: it lands under
    AppData/Local/Packages/PythonSoftwareFoundation.Python.../LocalCache.
    """
    from lt_ui.paths import actual_location

    real_place = tmp_path / "elsewhere"
    real_place.mkdir()
    link = tmp_path / "named"
    try:
        link.symlink_to(real_place, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("этой системе нельзя создать ссылку без прав")
    found, redirected = actual_location(link)
    assert redirected
    assert found == real_place.resolve()
