"""Day 7: the core speaking the language the interface is drawn in.

The window was translated and the pipeline was not, so a German user watched
«Распознаю (1.8 мин)» go by. The core cannot import the interface, and the
interface has no business rewriting the core's strings, so one function
connects them.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lt_core import messages
from lt_ui import i18n

CORE = Path(__file__).resolve().parent.parent / "lt_core"


@pytest.fixture(autouse=True)
def restore():
    language = i18n.LANGUAGE
    yield
    messages.install(None)
    i18n.set_language(language)


def test_without_an_interface_the_core_speaks_russian():
    """A command line whose every other word is Russian is the default."""
    messages.install(None)
    assert messages.say("Собираю субтитры") == "Собираю субтитры"


@pytest.mark.parametrize("language,expected", [
    ("en", "Building subtitles"),
    ("de", "Untertitel werden gebaut"),
    ("ru", "Собираю субтитры"),
])
def test_an_installed_translator_is_used(language, expected):
    i18n.set_language(language)
    messages.install(i18n.t)
    assert messages.say("Собираю субтитры") == expected


def test_a_language_name_in_a_stage_message_is_translated():
    """Otherwise a German window reads «Übersetzung nach русский»."""
    from lt_core.pipeline.batch import _named

    i18n.set_language("de")
    messages.install(i18n.t)
    assert _named("ru") == "Russisch"
    assert messages.say("Перевожу на {language}", language=_named("en")) == (
        "Übersetzung nach Englisch"
    )
    i18n.set_language("ru")
    messages.install(None)


@pytest.mark.parametrize("installed", [True, False])
def test_a_russian_stage_message_names_the_language_in_lowercase(installed):
    """Russian writes a language's name in lowercase inside a sentence; the
    Russian window was showing «Перевожу на Русский»."""
    from lt_core.pipeline.batch import _named

    i18n.set_language("ru")
    messages.install(i18n.t if installed else None)
    assert messages.say("Перевожу на {language}", language=_named("ru")) == (
        "Перевожу на русский"
    )
    i18n.set_language("en")
    messages.install(i18n.t)
    assert _named("de") == "German", "other languages keep their capital"


def test_values_are_filled_after_translating():
    """So a translation carries the placeholder, not a frozen number."""
    i18n.set_language("en")
    messages.install(i18n.t)
    assert messages.say("Распознаю ({minutes} мин)", minutes="1.8") == (
        "Recognising (1.8 min)"
    )


def test_a_broken_translator_does_not_stop_a_job():
    """A catalogue problem is worth a Russian label, not a failed recording."""

    def broken(_text: str) -> str:
        raise RuntimeError("каталог сломан")

    messages.install(broken)
    assert messages.say("Собираю субтитры") == "Собираю субтитры"


def test_every_message_the_core_asks_for_is_in_the_catalogue():
    """A message routed through the seam but missing from the catalogue shows
    Russian inside an English window -- which is the failure being fixed."""
    asked: set[str] = set()
    for path in sorted(CORE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"say", "tell"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                asked.add(node.args[0].value)
    missing = sorted(text for text in asked if text not in i18n.CATALOGUE)
    assert missing == [], missing


def test_the_core_does_not_import_the_interface():
    """The seam exists so that it does not have to. `lt_core` must keep
    running, and keep being testable, without `lt_ui` present at all."""
    offenders: list[str] = []
    for path in sorted(CORE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # Imports, not mentions: the seam's own docstring says the word
            # `lt_ui`, and a grep would fail on that forever.
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] == "lt_ui" for name in names):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], offenders


def test_a_stage_message_reaches_the_caller_translated():
    """The pipeline reports through `on_stage`; that is what a window shows."""
    from lt_core.media import MediaError, probe

    i18n.set_language("de")
    messages.install(i18n.t)
    with pytest.raises(MediaError) as caught:
        probe("нет-такого-файла.mp4")
    assert "nicht gefunden" in str(caught.value)
