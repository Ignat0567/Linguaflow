"""English words in German speech, put into German before NLLB sees them.

German talk about software is full of English nouns, and NLLB reads some of
them as German words or as nothing at all. Heard in a meeting, 2026-09-22:
«Und der zweite Link hier.» came out «И второе звено здесь.» -- a chain link.
Measured on the 1.3B model, one sentence each:

    Das Feature ist noch nicht fertig.   -> «Фильм еще не закончен.»
    ... auf ein Feature-Set geeinigt.    -> «...о полнометражном наборе.»
    Wir müssen das Onboarding verbessern -> «Мы должны улучшить набор.»

and with the German word put in first:

    Funktion       -> «Функция еще не готова», «...о наборе функций»
    Verweis        -> «ссылка», in every case and number tried
    Einarbeitung   -> «обучение»

Call, Meeting, Deadline, Tool, Workflow, Screen, Feedback and Use Case came
through right as they were, and are left alone.

The replacements are case-sensitive: lower-case «links» is German for
"on the left", and a sentence that opens with «Links» may mean the same, so
that one is not touched either.
"""

from __future__ import annotations

import re

#: source language -> (pattern, replacement), applied in order.
REPLACEMENTS: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "de": (
        (re.compile(r"\bFeatures\b"), "Funktionen"),
        (re.compile(r"\bFeature(?=-|\b)"), "Funktion"),
        # Not at the start of a sentence, where «Links» may be "left".
        (re.compile(r"(?<![.!?]\s)(?<!^)\bLinks\b"), "Verweise"),
        (re.compile(r"\bLink\b"), "Verweis"),
        (re.compile(r"\bOnboarding\b"), "Einarbeitung"),
    ),
}


def germanise(text: str, source: str) -> str:
    """`text` with the loanwords NLLB misreads replaced, for `source`."""
    for pattern, replacement in REPLACEMENTS.get(source, ()):
        text = pattern.sub(replacement, text)
    return text
