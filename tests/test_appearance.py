"""Day 7: the light theme, the interface language, and where files land."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lt_ui import i18n, theme
from lt_ui.store import Settings, Store, display_name

UI_ROOT = Path(__file__).resolve().parent.parent / "lt_ui"


@pytest.fixture(autouse=True)
def restore_globals():
    """Theme and language are process-wide; put them back after each test."""
    mode, language = theme.MODE, i18n.LANGUAGE
    yield
    theme.set_mode(mode)
    i18n.set_language(language)


# -- the catalogue -------------------------------------------------------

def test_every_string_is_translated_into_both_languages():
    """The answer to keying a catalogue on its source text.

    Nothing stops a new Russian string from being added with an empty English
    or German side except this.
    """
    assert i18n.missing() == []


def test_the_catalogue_covers_every_string_the_screens_ask_for():
    """A screen asking for a string that is not in the catalogue would show
    Russian inside a German window, which is the failure this prevents."""
    asked: set[str] = set()
    for path in sorted(UI_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                asked.add(node.args[0].value)
    missing = sorted(text for text in asked if text not in i18n.CATALOGUE)
    assert missing == [], missing


@pytest.mark.parametrize("language,expected", [
    ("ru", "Настройки"), ("en", "Settings"), ("de", "Einstellungen"),
])
def test_a_string_comes_back_in_the_chosen_language(language, expected):
    i18n.set_language(language)
    assert i18n.t("Настройки") == expected


def test_an_unknown_string_comes_back_as_russian_rather_than_empty():
    """Visibly wrong beats invisibly missing: a Russian label in a German
    window gets reported, an empty one looks like a layout bug."""
    i18n.set_language("de")
    assert i18n.t("Такой строки в каталоге нет") == "Такой строки в каталоге нет"


def test_an_unknown_interface_language_falls_back_to_russian():
    i18n.set_language("kl")
    assert i18n.LANGUAGE == "ru"


def test_parameters_are_filled_in_every_language():
    for language in i18n.UI_LANGUAGES:
        i18n.set_language(language)
        filled = i18n.t("Сохранено · {duration}", duration="07:33")
        assert "07:33" in filled
        assert "{duration}" not in filled


def test_translated_languages_are_named_in_the_interface_language():
    """The product translates languages; showing their names in only one of
    them would be a poor joke."""
    i18n.set_language("de")
    assert display_name("ru") == "Russisch"
    i18n.set_language("en")
    assert display_name("de") == "German"
    i18n.set_language("ru")
    assert display_name("de") == "Немецкий"


# -- the trap this cost twice -------------------------------------------

def test_no_caption_is_translated_at_import_time():
    """`_()` outside a function freezes the Russian text at import.

    It happened twice while this was being written: the nav bar kept its
    Russian captions while every other string changed language, and so did
    the online-service list. Both were class or module level constants, and
    both looked correct in the source.
    """
    frozen: list[str] = []

    def walk(node: ast.AST, path: Path, inside_function: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, path, True)
                continue
            if (
                not inside_function
                and isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "_"
            ):
                frozen.append(f"{path.name}:{child.lineno}")
            walk(child, path, inside_function)

    for path in sorted(UI_ROOT.rglob("*.py")):
        walk(ast.parse(path.read_text(encoding="utf-8")), path, False)
    assert frozen == [], frozen


# -- the light theme -----------------------------------------------------

def test_the_foreground_inverts_but_the_glass_does_not():
    """Frosted white over a bright photograph is still glass. What changes is
    the text and the scrim, and that distinction is the whole design."""
    theme.set_mode(theme.DARK)
    dark_text, dark_glass = theme.ink(1.0), theme.surface(0.5)
    theme.set_mode(theme.LIGHT)
    light_text, light_glass = theme.ink(1.0), theme.surface(0.5)

    assert dark_text.lightness() > light_text.lightness()
    assert dark_glass.rgb() == light_glass.rgb()


def test_the_light_theme_uses_a_pale_scrim_not_a_dark_one():
    theme.set_mode(theme.DARK)
    dark_rgb, _dark_stops = theme.scrim()
    theme.set_mode(theme.LIGHT)
    light_rgb, _light_stops = theme.scrim()
    assert sum(light_rgb) > sum(dark_rgb)


def test_panels_are_more_opaque_on_the_light_theme():
    """At 8% white a panel over a bright photograph reads as a smudge."""
    theme.set_mode(theme.DARK)
    dark = theme.tint()
    theme.set_mode(theme.LIGHT)
    assert theme.tint() > dark


def test_secondary_text_is_lifted_on_the_light_theme_only():
    theme.set_mode(theme.DARK)
    assert theme.text_alpha(theme.SECONDARY) == theme.SECONDARY
    theme.set_mode(theme.LIGHT)
    assert theme.text_alpha(theme.SECONDARY) > theme.SECONDARY


def test_primary_text_is_never_lifted_past_opaque():
    theme.set_mode(theme.LIGHT)
    assert theme.text_alpha(theme.PRIMARY) == 1.0


def test_text_on_an_accent_fill_stays_dark_in_both_themes():
    """Every accent is light enough that white text on it fails to read."""
    theme.set_mode(theme.DARK)
    on_dark = theme.on_accent()
    theme.set_mode(theme.LIGHT)
    assert on_dark == theme.on_accent()
    assert on_dark.lightness() < 60


def test_a_label_colour_follows_the_mode():
    theme.set_mode(theme.DARK)
    dark = theme.label_colour(theme.PRIMARY)
    theme.set_mode(theme.LIGHT)
    assert theme.label_colour(theme.PRIMARY) != dark


# -- settings that have to survive a restart ----------------------------

def test_appearance_and_language_are_remembered(tmp_path):
    store = Store(tmp_path)
    store.settings.appearance = "light"
    store.settings.ui_language = "de"
    store.save_settings()
    assert Store(tmp_path).settings.appearance == "light"
    assert Store(tmp_path).settings.ui_language == "de"


@pytest.mark.parametrize("field,bad,fallback", [
    ("appearance", "chartreuse", "dark"),
    ("ui_language", "kl", "ru"),
])
def test_a_nonsense_setting_falls_back(field, bad, fallback):
    settings = Settings()
    setattr(settings, field, bad)
    settings.clamp()
    assert getattr(settings, field) == fallback


# -- where files land ----------------------------------------------------

def test_by_default_each_job_gets_its_own_folder(tmp_path):
    store = Store(tmp_path)
    first, second = store.job_dir("aaa"), store.job_dir("bbb")
    assert first != second
    assert first.parent.name == "jobs"


def test_a_chosen_folder_is_used_as_given(tmp_path):
    """Someone who picks «Загрузки» wants the file in «Загрузки»."""
    chosen = tmp_path / "Переводы"
    chosen.mkdir()
    store = Store(tmp_path / "data")
    store.settings.output_dir = str(chosen)
    assert store.job_dir("aaa") == chosen
    assert store.job_dir("bbb") == chosen


def test_a_folder_that_has_gone_away_is_forgotten(tmp_path):
    """An unplugged drive must not stop a job halfway through writing."""
    store = Store(tmp_path)
    store.settings.output_dir = str(tmp_path / "removable" / "Subs")
    store.settings.clamp()
    assert store.settings.output_dir == ""


def test_a_chosen_folder_is_created_if_it_does_not_exist_yet(tmp_path):
    store = Store(tmp_path / "data")
    target = tmp_path / "new" / "place"
    store.settings.output_dir = str(target)
    assert store.job_dir("aaa") == target
    assert target.is_dir()
