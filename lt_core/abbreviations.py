"""Full stops that do not end a sentence.

«Mit diesen Workflows kannst du jetzt LLM mit Tools wie z.B.» was taken for a
whole sentence on a German video: the live session released it to the
translator at the «z.B.», which came back with an invented verb
(«моделировать LLM»), and the rest of the sentence was translated on its
own. The same full stop cut subtitles and the pieces handed to NLLB.

Only abbreviations that are practically never the last word of a sentence
are listed. «etc.», «usw.» and «ect.» often are, and a sentence that did end
on one would then wait for the next -- a smaller fault than a cut, but not
one worth making for them.
"""

from __future__ import annotations

import re

#: Lower-cased, dots included, as written.
ABBREVIATIONS = frozenset({
    # German
    "z.b.", "d.h.", "u.a.", "u.ä.", "o.ä.", "bzw.", "ca.", "vgl.", "evtl.",
    "ggf.", "inkl.", "zzgl.", "bspw.", "sog.", "nr.", "dr.", "prof.", "hr.",
    "fr.", "str.", "abs.", "s.o.", "s.u.", "z.t.", "i.d.r.",
    # English
    "e.g.", "i.e.", "vs.", "mr.", "mrs.", "ms.", "dr.", "prof.", "approx.",
    "st.", "jr.", "sr.",
    # French, Spanish, Italian
    "p.ex.", "mme.", "mlle.", "p.ej.", "sra.", "srta.", "ecc.", "sig.",
})

#: «z.» of «z. B.» when the recogniser spaces it, and initials: one letter
#: and a full stop is not the end of anyone's sentence.
_INITIAL = re.compile(r"^[^\W\d]\.$")


def is_abbreviation(word: str) -> bool:
    """Whether `word`, with its trailing full stop, is an abbreviation."""
    token = word.strip().strip("\"'«»„“”()[]").lower()
    return token in ABBREVIATIONS or bool(_INITIAL.match(token))
