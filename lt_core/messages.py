"""How the core speaks to whoever is watching.

The core has no business knowing about an interface, and an interface has no
business reaching into the core to rewrite its strings. What connects them is
one function: the core asks for a message here, and something outside may
install a translator for it.

Installed with nothing, it returns the Russian it was given. That is the right
default for a command line whose every other word is Russian, and it is why
this is a seam rather than a dependency: `lt_core` still imports nothing from
`lt_ui`, and the tests of either run without the other.

Only the messages a person actually reads go through it -- the stages of a job
and the errors that stop one. Log detail, exception payloads and the internal
strings that never reach a screen are left alone.
"""

from __future__ import annotations

from collections.abc import Callable

#: Set by whoever knows what language the user is reading in.
_translator: Callable[[str], str] | None = None


def install(translator: Callable[[str], str] | None) -> None:
    """Route messages through `translator`, or back to Russian with None."""
    global _translator
    _translator = translator


def say(text: str, **values: object) -> str:
    """The message in whatever language has been installed.

    Values are filled in after translating, so a translation keeps the
    placeholders rather than the numbers -- and a translation that loses one
    shows the brace rather than silently dropping the figure.
    """
    if _translator is not None:
        try:
            text = _translator(text)
        except Exception:  # noqa: BLE001 -- a broken catalogue is not a crash
            pass
    return text.format(**values) if values else text
