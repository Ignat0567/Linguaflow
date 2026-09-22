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

Found on a real German video about AI agents, the same day: «Prompt» came
out «проспект», «предложение», «призыв», and «LLMs mit Tools» «степень
магистра», the law degree. «LLM-Modell» keeps the letters and reads
«LLM-модель». For «Prompt» see `germanise`.

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
        (re.compile(r"\bLLMs\b"), "LLM-Modelle"),
        (re.compile(r"\bLLM\b(?!-)"), "LLM-Modell"),
    ),
}

_PROMPT = re.compile(r"\bPrompt(s)?\b")
#: German words for a question or a request. A sentence that already has
#: one keeps «Prompt» as a name, because its «вопрос» / «запрос» is real.
_OWN_QUESTION = re.compile(r"(?i)\w*(?:frage|anfrage|abfrage)n?\b")
#: «промпт» declines as «запрос» and «вопрос» do -- a hard masculine stem --
#: so the model's own case ending carries over to it.
_STAND_IN = re.compile(r"\b([ЗзВв])(?:апрос|опрос)(а|у|ом|е|ы|ов|ам|ами|ах)?\b")

#: What a term kept in capitals becomes in the translation, by target.
RESTORED: tuple[tuple[re.Pattern[str], dict[str, str]], ...] = (
    (re.compile(r"\b(?:PROMPTS|ПРОМПТЫ)\b"), {"ru": "промпты", "": "prompts"}),
    (re.compile(r"\b(?:PROMPT|ПРОМПТ[А-Я]{0,3})\b"), {"ru": "промпт", "": "prompt"}),
)


def germanise(text: str, source: str, target: str = "ru") -> str:
    """`text` with the loanwords NLLB misreads replaced, for `source`.

    «Prompt» is the odd one: no German word comes back as «промпт». Into
    Russian it becomes «Abfrage», which the model renders «запрос» (7 of 9
    sentences) or «вопрос» (2 of 9) in whatever case the sentence needs,
    and `restore` swaps the stem: «инженерия запросов» -> «инженерия
    промптов». Where the sentence has its own Frage/Anfrage, or the target
    is not Russian, it is written in capitals instead, which the model
    keeps as a name -- right, if undeclined.
    """
    for pattern, replacement in REPLACEMENTS.get(source, ()):
        text = pattern.sub(replacement, text)
    if source == "de" and _PROMPT.search(text):
        if target == "ru" and not _OWN_QUESTION.search(text):
            text = _PROMPT.sub(lambda m: "Abfragen" if m.group(1) else "Abfrage", text)
        else:
            text = _PROMPT.sub(lambda m: "PROMPTS" if m.group(1) else "PROMPT", text)
    return text


def restore(text: str, original: str, source: str, target: str) -> str:
    """The translation of `original` with `germanise`'s stand-ins undone."""
    if source not in REPLACEMENTS:
        return text
    if target == "ru" and source == "de" and not _OWN_QUESTION.search(original):
        count = len(_PROMPT.findall(original))
        if count:
            def to_prompt(match: re.Match[str]) -> str:
                head = "П" if match.group(1).isupper() else "п"
                return f"{head}ромпт{match.group(2) or ''}"

            text = _STAND_IN.sub(to_prompt, text, count=count)
    for pattern, words in RESTORED:
        text = pattern.sub(words.get(target, words[""]), text)
    return text
