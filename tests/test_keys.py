"""Day 7: each user's own API key, on their own machine.

The product is meant to be installed, so a key belongs to whoever is sitting
at the computer -- not to the program, not to the settings file, and not to
whoever gets a copy of the folder.
"""

from __future__ import annotations

import json

import pytest

from lt_ui.keys import KeyStore, available, protection
from lt_ui.store import Store

KEY = "nvapi-not-a-real-key-0123456789"


def test_a_fresh_installation_has_no_keys(tmp_path):
    """Absent is the normal state, not an error to be handled."""
    store = KeyStore(tmp_path)
    assert store.get("nvidia") == ""
    assert not store.has("nvidia")
    assert store.services() == []


def test_a_key_survives_being_written_and_read(tmp_path):
    store = KeyStore(tmp_path)
    store.set("nvidia", KEY)
    assert KeyStore(tmp_path).get("nvidia") == KEY


def test_the_key_is_not_in_the_file_in_readable_form(tmp_path):
    """Whatever the platform offers, the file must not simply spell it out
    where encryption is available."""
    store = KeyStore(tmp_path)
    store.set("nvidia", KEY)
    raw = (tmp_path / "keys.dat").read_text(encoding="utf-8")
    if available():
        assert KEY not in raw
    assert json.loads(raw)


def test_keys_live_apart_from_the_settings(tmp_path):
    """settings.json is rewritten on every toggle and gets copied around; a
    key has no business being in it."""
    store = Store(tmp_path)
    store.keys.set("nvidia", KEY)
    store.save_settings()
    assert KEY not in (tmp_path / "settings.json").read_text(encoding="utf-8")


def test_each_service_keeps_its_own(tmp_path):
    store = KeyStore(tmp_path)
    store.set("nvidia", "nvapi-one")
    store.set("groq", "gsk-two")
    assert store.get("nvidia") == "nvapi-one"
    assert store.get("groq") == "gsk-two"
    assert store.services() == ["groq", "nvidia"]


def test_a_key_can_be_taken_back(tmp_path):
    store = KeyStore(tmp_path)
    store.set("nvidia", KEY)
    store.forget("nvidia")
    assert store.get("nvidia") == ""
    assert "nvidia" not in store.services()


def test_setting_an_empty_key_removes_it(tmp_path):
    store = KeyStore(tmp_path)
    store.set("nvidia", KEY)
    store.set("nvidia", "   ")
    assert not store.has("nvidia")


def test_surrounding_whitespace_is_ignored(tmp_path):
    """A key pasted from a web page arrives with a newline on it."""
    store = KeyStore(tmp_path)
    store.set("nvidia", f"  {KEY}\n")
    assert store.get("nvidia") == KEY


# -- what happens when the file is wrong --------------------------------

def test_a_damaged_file_reads_as_no_key_rather_than_a_crash(tmp_path):
    (tmp_path / "keys.dat").write_text('{"nvidia": "not base64 at all"}',
                                       encoding="utf-8")
    assert KeyStore(tmp_path).get("nvidia") == ""


def test_a_file_that_is_not_json_reads_as_no_key(tmp_path):
    (tmp_path / "keys.dat").write_text("nonsense", encoding="utf-8")
    assert KeyStore(tmp_path).get("nvidia") == ""


def test_a_list_where_an_object_belongs_reads_as_no_key(tmp_path):
    (tmp_path / "keys.dat").write_text("[1, 2, 3]", encoding="utf-8")
    assert KeyStore(tmp_path).get("nvidia") == ""


@pytest.mark.skipif(not available(), reason="DPAPI отсутствует на этой системе")
def test_a_key_sealed_elsewhere_does_not_open_here(tmp_path):
    """The point of sealing it: copying the folder does not copy the key.

    A blob that this account did not create cannot be opened by it, and that
    reads as «no key» rather than as a fault.
    """
    import base64

    foreign = base64.b64encode(b"\x01\x00\x00\x00sealed somewhere else").decode()
    (tmp_path / "keys.dat").write_text(json.dumps({"nvidia": foreign}),
                                       encoding="utf-8")
    assert KeyStore(tmp_path).get("nvidia") == ""


def test_the_protection_in_force_is_reported(tmp_path):
    """The interface tells the user which of the two they have, so it has to
    be answerable."""
    assert protection() in {"dpapi", "plain"}


# -- showing it back ----------------------------------------------------

def test_a_stored_key_is_shown_masked():
    masked = KeyStore.masked(KEY)
    assert KEY not in masked
    assert masked.startswith(KEY[:6])
    assert masked.endswith(KEY[-4:])


def test_a_short_key_shows_nothing_of_itself():
    assert set(KeyStore.masked("abc123")) == {"•"}


def test_no_key_masks_to_nothing():
    assert KeyStore.masked("") == ""


# -- what the app does with it ------------------------------------------

def test_the_shortener_is_built_with_the_stored_key(tmp_path):
    from lt_ui.engine import _shortener

    store = Store(tmp_path)
    store.settings.shorten_with = "nvidia"
    store.keys.set("nvidia", KEY)
    provider = _shortener(store.settings, store.keys)
    assert provider is not None
    assert provider.api_key == KEY


def test_without_a_service_chosen_nothing_is_built(tmp_path):
    from lt_ui.engine import _shortener

    store = Store(tmp_path)
    store.settings.shorten_with = ""
    assert _shortener(store.settings, store.keys) is None


def test_a_service_with_no_key_does_not_stop_the_job(tmp_path, monkeypatch):
    """Choosing a service the machine cannot reach costs a warning, not a
    recording: the job goes ahead on the rules alone."""
    from lt_ui.engine import _shortener

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    store = Store(tmp_path)
    store.settings.shorten_with = "nvidia"
    assert _shortener(store.settings, store.keys) is None
