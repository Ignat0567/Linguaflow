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
    #: ISO 639-2, which is what a media container labels a track with.
    iso3: str
    #: DeepL's own code. It rejects a plain "EN" as a target, hence the pair.
    deepl_source: str
    deepl_target: str
    #: Written without spaces between words, which changes how subtitles are
    #: measured, wrapped and joined.
    scriptio_continua: bool = False
    #: A Piper voice that exists for this language, for spoken output.
    piper_voice: str = ""
    #: A pair of voices for dubbing a recording with more than one speaker in
    #: it, so a man is not read out in a woman's voice.
    #:
    #: Chosen by measuring, not by the name in the file. Piper publishes no
    #: gender for its voices, and the obvious guesses were wrong: the Russian
    #: default `dmitri` measures at 186 Hz -- inside the female range -- and
    #: `irina` at 177 Hz, so that pair would have sounded like one person.
    #: Every candidate for these three languages was synthesised on the same
    #: sentence and its fundamental frequency measured; the numbers are in
    #: `docs/DAY7.md`.
    piper_male: str = ""
    piper_female: str = ""
    #: A short, properly punctuated sample, given to the recogniser as its
    #: opening context.
    #:
    #: Whisper copies the style of whatever it is primed with, and given
    #: nothing it transcribes fast continuous speech as one unpunctuated run.
    #: Measured on a real recording: one sentence end per 2227 characters
    #: without this, thirteen with it. It is written in each language because
    #: a prompt in the wrong language is the one way this is known to do harm.
    punctuation_sample: str = ""


CATALOGUE: dict[str, Language] = {
    "ru": Language(
        "ru", "русский", "Russian", "rus_Cyrl", "rus", "RU", "RU",
        piper_voice="ru_RU-dmitri-medium",
        piper_male="ru_RU-ruslan-medium",      # 128 Hz
        # terra, not Piper's own irina: see EXTRA_VOICES in lt_core.tts.speaker.
        piper_female="ru_RU-terra5871-medium",  # 208 Hz
        punctuation_sample=(
            "Здравствуйте. Сегодня мы разберём несколько важных вопросов, а затем перейдём к примерам. Начнём?"
        ),
    ),
    "en": Language(
        "en", "английский", "English", "eng_Latn", "eng", "EN", "EN-GB",
        piper_voice="en_US-lessac-medium",
        piper_male="en_US-hfc_male-medium",    # 114 Hz
        piper_female="en_US-lessac-medium",    # 198 Hz
        punctuation_sample=(
            "Hello, and welcome. Today we will go through a few important points, and then look at some examples. Shall we begin?"
        ),
    ),
    "de": Language(
        "de", "немецкий", "German", "deu_Latn", "deu", "DE", "DE",
        piper_voice="de_DE-thorsten-medium",
        piper_male="de_DE-thorsten-medium",    # 131 Hz
        piper_female="de_DE-ramona-low",       # 191 Hz
        punctuation_sample=(
            "Guten Tag. Heute gehen wir einige wichtige Punkte durch, und danach sehen wir uns Beispiele an. Fangen wir an?"
        ),
    ),
    # -- not offered yet; every path below is written and tested ----------
    "zh": Language(
        "zh", "китайский", "Chinese", "zho_Hans", "zho", "ZH", "ZH",
        scriptio_continua=True, piper_voice="zh_CN-huayan-medium",
        punctuation_sample=(
            "大家好。今天我们先看几个重点，然后再看一些例子。我们开始吧？"
        ),
    ),
    "ja": Language(
        "ja", "японский", "Japanese", "jpn_Jpan", "jpn", "JA", "JA",
        scriptio_continua=True, piper_voice="ja_JA-hi_fi_captain-medium",
        punctuation_sample=(
            "こんにちは。今日はいくつかの重要な点を見てから、例を確認します。始めましょうか？"
        ),
    ),
    "es": Language(
        "es", "испанский", "Spanish", "spa_Latn", "spa", "ES", "ES",
        piper_voice="es_ES-davefx-medium",
        punctuation_sample=(
            "Hola, y bienvenidos. Hoy veremos algunos puntos importantes, y después algunos ejemplos. ¿Empezamos?"
        ),
    ),
    "it": Language(
        "it", "итальянский", "Italian", "ita_Latn", "ita", "IT", "IT",
        piper_voice="it_IT-paola-medium",
        punctuation_sample=(
            "Salve, e benvenuti. Oggi vedremo alcuni punti importanti, e poi qualche esempio. Cominciamo?"
        ),
    ),
    "fr": Language(
        "fr", "французский", "French", "fra_Latn", "fra", "FR", "FR",
        piper_voice="fr_FR-siwis-medium",
        punctuation_sample=(
            "Bonjour, et bienvenue. Aujourd'hui, nous verrons quelques points importants, puis des exemples. Commençons ?"
        ),
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


def voice_for(code: str, gender: str = "") -> str:
    """The Piper voice for a language, for a given gender where one exists.

    Falls back to the language's single voice rather than to the other
    gender's: reading a man in a woman's voice is the mistake this is here to
    avoid, and a language with no pair should simply not pretend to have one.
    """
    language = CATALOGUE.get(code)
    if language is None:
        return ""
    if gender == "male" and language.piper_male:
        return language.piper_male
    if gender == "female" and language.piper_female:
        return language.piper_female
    return language.piper_voice


def has_voice_pair(code: str) -> bool:
    """Whether this language can dub two speakers in different voices."""
    language = CATALOGUE.get(code)
    if language is None:
        return False
    return bool(
        language.piper_male
        and language.piper_female
        and language.piper_male != language.piper_female
    )


def track_language(code: str) -> str:
    """The code a media container labels an audio or subtitle track with."""
    language = CATALOGUE.get(code)
    return language.iso3 if language else "und"


def punctuation_sample(code: str) -> str:
    """The opening context the recogniser is primed with, in `code`."""
    language = CATALOGUE.get(code)
    return language.punctuation_sample if language else ""


def offered_list() -> str:
    """For an error message that has to say what the choices are."""
    return ", ".join(
        f"{code} ({language.name})" for code, language in active().items()
    )
