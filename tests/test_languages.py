"""The language registry, and the switch that widens it."""

from __future__ import annotations

import importlib

import pytest

from lt_core import languages


def test_this_build_offers_three():
    assert set(languages.ACTIVE) == {"ru", "en", "de"}


def test_the_catalogue_is_wider_than_the_build():
    """The other five are kept, not deleted.

    Their code paths -- CJK line breaking, reading speeds, sentence splitting,
    numeral scales for the translation audit -- are written and tested.
    Removing them to ship three languages would mean writing them again to
    ship five more.
    """
    assert set(languages.CATALOGUE) > set(languages.ACTIVE)


@pytest.mark.parametrize("code", sorted(languages.CATALOGUE))
def test_every_catalogue_entry_is_complete(code):
    """A half-filled entry fails at the moment someone enables it."""
    language = languages.CATALOGUE[code]
    assert language.code == code
    assert language.name and language.english_name
    assert language.nllb and "_" in language.nllb
    assert language.deepl_source and language.deepl_target
    assert language.piper_voice


def test_an_inactive_language_is_still_describable():
    """A Spanish recording should be reported as Spanish, not as a raw code."""
    assert not languages.is_active("es")
    assert languages.describe("es") == "испанский"


def test_an_unknown_code_describes_as_itself():
    assert languages.describe("xx") == "xx"


def test_cjk_is_marked_as_written_without_spaces():
    assert not languages.joins_with_space("zh")
    assert not languages.joins_with_space("ja")
    assert languages.joins_with_space("ru")
    assert languages.joins_with_space("de")


def test_unknown_codes_join_with_spaces():
    """The safer default: a wrong space is visible, a missing one is not."""
    assert languages.joins_with_space("xx")


# -- the escape hatch ----------------------------------------------------

def test_the_environment_can_widen_the_build(monkeypatch):
    """Adding a language back must not need a code change."""
    monkeypatch.setenv("LINGUAFLOW_LANGUAGES", "ru,en,de,zh")
    reloaded = importlib.reload(languages)
    try:
        assert reloaded.is_active("zh")
        assert "китайский" in reloaded.offered_list()
    finally:
        monkeypatch.delenv("LINGUAFLOW_LANGUAGES")
        importlib.reload(languages)


def test_widening_reaches_the_rest_of_the_stack(monkeypatch):
    """The switch is worthless if only this module honours it."""
    monkeypatch.setenv("LINGUAFLOW_LANGUAGES", "ru,en,de,ja")
    importlib.reload(languages)
    transcriber = importlib.reload(
        importlib.import_module("lt_core.asr.transcriber")
    )
    try:
        assert "ja" in transcriber.SUPPORTED_LANGUAGES
    finally:
        monkeypatch.delenv("LINGUAFLOW_LANGUAGES")
        importlib.reload(languages)
        importlib.reload(transcriber)


def test_nonsense_in_the_variable_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("LINGUAFLOW_LANGUAGES", "klingon, ,elvish")
    reloaded = importlib.reload(languages)
    try:
        assert reloaded.ACTIVE == reloaded.DEFAULT_ACTIVE
    finally:
        monkeypatch.delenv("LINGUAFLOW_LANGUAGES")
        importlib.reload(languages)


def test_the_variable_accepts_loose_formatting(monkeypatch):
    monkeypatch.setenv("LINGUAFLOW_LANGUAGES", " RU ; en ,DE ")
    reloaded = importlib.reload(languages)
    try:
        assert reloaded.ACTIVE == ("ru", "en", "de")
    finally:
        monkeypatch.delenv("LINGUAFLOW_LANGUAGES")
        importlib.reload(languages)


# -- no second list anywhere --------------------------------------------

def test_translation_codes_cover_the_whole_catalogue():
    """Enabling a language must not require editing the translator too."""
    from lt_core.mt.types import NLLB_CODES

    assert set(NLLB_CODES) == set(languages.CATALOGUE)


def test_cloud_codes_cover_the_whole_catalogue():
    from lt_core.mt.cloud import _DEEPL_SOURCE, _DEEPL_TARGET, _LANGUAGE_NAMES

    for table in (_DEEPL_SOURCE, _DEEPL_TARGET, _LANGUAGE_NAMES):
        assert set(table) == set(languages.CATALOGUE)


def test_deepl_target_english_is_a_variant():
    """DeepL rejects a plain "EN" as a target and accepts EN-GB or EN-US."""
    assert languages.CATALOGUE["en"].deepl_target != "EN"
