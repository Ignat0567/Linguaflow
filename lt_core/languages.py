"""Which languages Linguaflow offers, and everything each one needs.

Until now this knowledge was spread across four modules -- the recogniser knew
the display names, the translator knew the NLLB codes, the cloud providers knew
DeepL's codes, and the subtitle layer knew which scripts are written without
spaces. Four partial lists of the same thing, which is three opportunities for
them to disagree.

They are one list now, and that list is also the switch. The product ships with
Russian, English and German. The other five are written out in full and simply
not offered: every code path they need already exists and is tested -- Chinese
and Japanese line breaking, their reading speeds, CJK sentence splitting, the
numeral scales the translation audit understands. Deleting that work to ship
three languages would mean writing it again to ship five more.

Turning one back on is one entry in `ACTIVE`, or one environment variable:

    LINGUAFLOW_LANGUAGES=ru,en,de,zh
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    #: Shown to the user.
    name: str
    #: Used when a prompt has to name the language to a model that reads English.
    english_name: str
    #: NLLB distinguishes script: rus_Cyrl, not rus_Latn.
    nllb: str
    #: DeepL's own code. It rejects a plain "EN" as a target, hence the pair.
    deepl_source: str
    deepl_target: str
    #: Written without spaces between words, which changes how subtitles are
    #: measured, wrapped and joined.
    scriptio_continua: bool = False
    #: A Piper voice that exists for this language, for spoken output.
    piper_voice: str = ""


CATALOGUE: dict[str, Language] = {
    "ru": Language(
        "ru", "русский", "Russian", "rus_Cyrl", "RU", "RU",
        piper_voice="ru_RU-dmitri-medium",
    ),
    "en": Language(
        "en", "английский", "English", "eng_Latn", "EN", "EN-GB",
        piper_voice="en_US-lessac-medium",
    ),
    "de": Language(
        "de", "немецкий", "German", "deu_Latn", "DE", "DE",
        piper_voice="de_DE-thorsten-medium",
    ),
    # -- not offered yet; every path below is written and tested ----------
    "zh": Language(
        "zh", "китайский", "Chinese", "zho_Hans", "ZH", "ZH",
        scriptio_continua=True, piper_voice="zh_CN-huayan-medium",
    ),
    "ja": Language(
        "ja", "японский", "Japanese", "jpn_Jpan", "JA", "JA",
        scriptio_continua=True, piper_voice="ja_JA-hi_fi_captain-medium",
    ),
    "es": Language(
        "es", "испанский", "Spanish", "spa_Latn", "ES", "ES",
        piper_voice="es_ES-davefx-medium",
    ),
    "it": Language(
        "it", "итальянский", "Italian", "ita_Latn", "IT", "IT",
        piper_voice="it_IT-paola-medium",
    ),
    "fr": Language(
        "fr", "французский", "French", "fra_Latn", "FR", "FR",
        piper_voice="fr_FR-siwis-medium",
    ),
}

#: What this build offers. Three to begin with, so that each is measured
#: properly rather than eight being claimed and none checked.
DEFAULT_ACTIVE = ("ru", "en", "de")


def _from_environment() -> tuple[str, ...] | None:
    raw = os.environ.get("LINGUAFLOW_LANGUAGES", "").strip()
    if not raw:
        return None
    codes = tuple(
        code.strip().lower() for code in raw.replace(";", ",").split(",")
        if code.strip()
    )
    known = tuple(code for code in codes if code in CATALOGUE)
    return known or None


ACTIVE: tuple[str, ...] = _from_environment() or DEFAULT_ACTIVE


def active() -> dict[str, Language]:
    """The languages this build offers, in the order they are listed."""
    return {code: CATALOGUE[code] for code in ACTIVE if code in CATALOGUE}


def names() -> dict[str, str]:
    """Code to display name, for pickers and messages."""
    return {code: language.name for code, language in active().items()}


def get(code: str) -> Language | None:
    """A language by code, whether or not this build offers it.

    Deliberately not restricted to the active set: a file recorded in Spanish
    should be *reported* as Spanish, with a note that it is outside what has
    been measured, rather than as an unknown code.
    """
    return CATALOGUE.get(code)


def is_active(code: str) -> bool:
    return code in ACTIVE


def describe(code: str) -> str:
    language = CATALOGUE.get(code)
    return language.name if language else code


def joins_with_space(code: str) -> bool:
    """Whether words in this language are separated by spaces when joined.

    Asked in three places -- reassembling a translation, distributing one
    across cues, wrapping a line -- and each had its own literal {"zh", "ja"}.
    A language added to the catalogue should not require finding all three.
    """
    language = CATALOGUE.get(code)
    return not (language and language.scriptio_continua)


def offered_list() -> str:
    """For an error message that has to say what the choices are."""
    return ", ".join(
        f"{code} ({language.name})" for code, language in active().items()
    )
