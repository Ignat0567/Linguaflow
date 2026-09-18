"""Shortening a translation so that it can be said in the time available.

A dub has a hard constraint subtitles do not: the words have to be spoken
inside the slot the original occupied. Speaking faster buys 15-20% and then
the voice stops sounding like a person, and Russian runs longer than English
to begin with, so on a fast speaker most lines overrun however they are asked.

The remaining lever is the text. Speech carries a great deal that is not
information -- discourse markers, doubled intensifiers, long connectives that
have short equivalents -- and removing those shortens a line without changing
what it says. That is the whole of what this does. It does not summarise, it
does not paraphrase, and it stops the moment the line fits.

Two things are never touched, and both are checked rather than trusted:

* **Numbers.** A dub that says a different figure is worse than one that runs
  over, and the same audit that guards the translation guards this.
* **Negation.** Dropping «не» inverts the sentence. Any rule that would remove
  or cross a negation is refused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .numbers import extract

#: Words that mark the rhythm of speech and carry no content. Removing one
#: changes how a sentence sounds and not what it says.
FILLERS: dict[str, tuple[str, ...]] = {
    "ru": (
        "вы знаете", "знаете ли", "знаете", "понимаете", "как бы",
        "в общем-то", "в общем", "на самом деле", "собственно говоря",
        "собственно", "так сказать", "если честно", "честно говоря",
        "скажем так", "я имею в виду", "в принципе", "как говорится",
        "видите ли", "согласитесь",
    ),
    "en": (
        "you know", "you see", "i mean", "actually", "basically",
        "literally", "sort of", "kind of", "to be honest", "as it were",
        "if you will", "so to speak", "of course",
    ),
    "de": (
        "wissen sie", "sehen sie", "ich meine", "eigentlich", "sozusagen",
        "quasi", "gewissermaßen", "ehrlich gesagt", "im grunde genommen",
        "im grunde", "natürlich",
    ),
}

#: Intensifiers. One is emphasis; the second is padding, so only repeats and
#: stacked pairs are removed.
INTENSIFIERS: dict[str, tuple[str, ...]] = {
    "ru": ("очень", "просто", "действительно", "реально", "буквально",
           "прямо", "совершенно", "абсолютно", "весьма", "довольно"),
    "en": ("very", "really", "just", "quite", "pretty", "absolutely",
           "completely", "totally"),
    "de": ("sehr", "wirklich", "einfach", "ganz", "völlig", "absolut",
           "ziemlich"),
}

#: Long forms and their shorter equivalents.
#:
#: Restricted to phrases that agree with nothing around them. The first
#: version of this table substituted nouns as well -- «программное
#: обеспечение» for «программа» -- and produced «открыть программа», because
#: Russian inflects and the replacement arrived in the nominative while the
#: sentence wanted the accusative. A line that does not fit its slot is a
#: smaller fault than a line in the wrong case, so anything that agrees with
#: its surroundings was taken back out. What is left are conjunctions,
#: adverbials, whole predicates, and two quantifiers that govern the same
#: case as the phrases they replace.
REPLACEMENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "ru": (
        # Only phrases that agree with nothing around them: conjunctions,
        # adverbials, whole predicates. Substituting a noun does not work in
        # an inflected language and the attempt is recorded above.
        ("для того чтобы", "чтобы"),
        ("в том случае если", "если"),
        ("по той причине что", "потому что"),
        ("в связи с тем что", "так как"),
        ("несмотря на то что", "хотя"),
        ("в настоящее время", "сейчас"),
        ("на данный момент", "сейчас"),
        ("на сегодняшний день", "сегодня"),
        ("в конечном итоге", "в итоге"),
        ("по сути дела", "по сути"),
        ("таким образом", "так"),
        ("имеет возможность", "может"),
        ("не имеет возможности", "не может"),
        # Both govern the genitive, so the noun after them does not move.
        ("большое количество", "много"),
        ("огромное количество", "множество"),
        # Clause openings, found by counting what this translator produces.
        ("вы можете видеть, что", "видно, что"),
        ("вы можете видеть", "видно"),
        ("к следующему шагу", "дальше"),
    ),
    "en": (
        ("in order to", "to"),
        ("due to the fact that", "because"),
        ("in spite of the fact that", "although"),
        ("at this point in time", "now"),
        ("a large number of", "many"),
        ("has the ability to", "can"),
        ("is able to", "can"),
        ("in the event that", "if"),
        ("as a matter of fact", "in fact"),
    ),
    "de": (
        ("aufgrund der tatsache dass", "weil"),
        ("zum gegenwärtigen zeitpunkt", "jetzt"),
        ("eine große anzahl von", "viele"),
        ("in der lage sein zu", "können"),
        ("für den fall dass", "falls"),
        ("darüber hinaus", "außerdem"),
    ),
}

#: Negation, in every language offered. A rule that would delete one of these,
#: or reach across one, is refused.
NEGATIONS: dict[str, tuple[str, ...]] = {
    "ru": ("не", "ни", "нет", "без"),
    "en": ("not", "no", "never", "n't", "without"),
    "de": ("nicht", "kein", "keine", "keinen", "nie", "ohne"),
}


@dataclass
class Condensed:
    """What a line became, and what was done to it."""

    text: str
    original: str
    #: Which rules fired, in order, for a report that can be checked.
    steps: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.text != self.original

    @property
    def saved(self) -> int:
        return len(self.original) - len(self.text)

    @property
    def ratio(self) -> float:
        return len(self.text) / len(self.original) if self.original else 1.0


def _tidy(text: str) -> str:
    """Close the gaps a removal leaves behind."""
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
    text = re.sub(r"([,;:])\s*([,.;:!?…])", r"\2", text)
    text = re.sub(r"^[\s,;:]+", "", text)
    text = re.sub(r"\(\s*\)", "", text)
    return text.strip()


def _safe(before: str, after: str, language: str) -> bool:
    """Whether a change kept the figures and the negations intact."""
    if not after.strip():
        return False
    if extract(before) != extract(after):
        return False
    negations = NEGATIONS.get(language, ())
    lower_before, lower_after = f" {before.lower()} ", f" {after.lower()} "
    for word in negations:
        if lower_before.count(f" {word} ") != lower_after.count(f" {word} "):
            return False
    return True


def _recase(candidate: str, original: str) -> str:
    """Restore the opening capital a removal at the start would have eaten.

    Dropping «Вы знаете,» from the front of a sentence leaves it starting in
    lower case, which reads as a fragment and, in a subtitle, as a mistake.
    """
    if not candidate or not original or not original[:1].isupper():
        return candidate
    return candidate[0].upper() + candidate[1:]


def _apply(text: str, pattern: re.Pattern, replacement: str, language: str) -> str:
    """Apply one rule, and keep the result only if it is safe."""
    candidate = _recase(_tidy(pattern.sub(replacement, text)), text)
    return candidate if _safe(text, candidate, language) else text


def _word_pattern(phrase: str) -> re.Pattern:
    escaped = r"\s+".join(re.escape(part) for part in phrase.split())
    return re.compile(rf"(?<!\w){escaped}(?!\w)[,]?", re.IGNORECASE)


def _phrase_pattern(phrase: str) -> re.Pattern:
    escaped = r"\s+".join(re.escape(part) for part in phrase.split())
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


def condense(text: str, budget: int, language: str = "ru") -> Condensed:
    """Shorten `text` towards `budget` characters, stopping once it fits.

    The order is deliberate: the rules that remove nothing of substance run
    first, and each is checked before it is kept. A line that fits is returned
    untouched, so nothing is shortened for its own sake.
    """
    result = Condensed(text=text, original=text)
    if budget <= 0 or len(text) <= budget:
        return result

    # 1. Long forms with short equivalents. These say the same thing, so they
    #    run first and are worth doing even where the saving is small.
    for long_form, short_form in REPLACEMENTS.get(language, ()):
        if len(result.text) <= budget:
            return result
        candidate = _apply(
            result.text, _phrase_pattern(long_form), short_form, language
        )
        if candidate != result.text:
            result.text = candidate
            result.steps.append(f"«{long_form}» → «{short_form}»")

    # 2. Discourse markers. Longest first, so "в общем-то" is not half-eaten
    #    by "в общем".
    for filler in sorted(FILLERS.get(language, ()), key=len, reverse=True):
        if len(result.text) <= budget:
            return result
        candidate = _apply(result.text, _word_pattern(filler), "", language)
        if candidate != result.text:
            result.text = candidate
            result.steps.append(f"убрано «{filler}»")

    # 3. Intensifiers, one at a time and only while the line is still too
    #    long. Emphasis is part of what a speaker meant, so this is the last
    #    thing tried and the first thing to stop.
    for word in INTENSIFIERS.get(language, ()):
        if len(result.text) <= budget:
            return result
        candidate = _apply(result.text, _word_pattern(word), "", language)
        if candidate != result.text:
            result.text = candidate
            result.steps.append(f"убрано «{word}»")

    return result


def slot_seconds(cues, index: int) -> float:
    """How long line `index` really has: until the next one starts.

    A cue ends when its words end, not when the next begins, and the silence
    between them is time the dub can use without colliding with anything.
    Free, and lossless -- nothing about the text changes. Measured on a real
    recording it took the lines that do not fit from 75 to 59 on its own.
    """
    cue = cues[index]
    if index + 1 < len(cues):
        return max(0.0, cues[index + 1].start - cue.start)
    return max(0.0, cue.end - cue.start)


def budgets_for(cues, chars_per_second: float, headroom: float,
                overhead: float, measure=None) -> list[int]:
    """The character budget for each line.

    With `measure` -- a function that says how long the voice actually takes
    over a piece of text -- the budget is derived from that measurement rather
    than from a formula. It is worth the extra synthesis: a linear model
    fitted to two probes said only 17 lines were too long where the
    synthesiser then overran on 86, because short lines are spoken more slowly
    per character than long ones and no single rate describes both.
    """
    budgets: list[int] = []
    for index, cue in enumerate(cues):
        slot = slot_seconds(cues, index)
        text = cue.flat_text
        if measure is not None and text.strip():
            natural = measure(text)
            allowed = slot * headroom
            if natural <= allowed or natural <= 0:
                budgets.append(len(text))
            else:
                budgets.append(max(1, int(len(text) * allowed / natural)))
        else:
            budgets.append(budget_for(slot, chars_per_second, headroom, overhead))
    return budgets


def condense_cues(cues, language: str, chars_per_second: float,
                  headroom: float = 1.0,
                  overhead: float = 0.0,
                  measure=None) -> tuple[list, list[Condensed]]:
    """Shorten whichever lines cannot be spoken in the time they have.

    Returns the cues with their text replaced, and the record of what was
    done, so a caller can report it rather than change the words silently.
    """
    from dataclasses import replace

    from ..subtitles.cues import CueStyle, _wrap

    style = CueStyle.for_language(language)
    budgets = budgets_for(cues, chars_per_second, headroom, overhead, measure)
    out, records = [], []
    for index, cue in enumerate(cues):
        text = cue.flat_text
        result = condense(text, budgets[index], language)
        records.append(result)
        if result.changed:
            cue = replace(cue, lines=_wrap(result.text, style))
        out.append(cue)
    return out, records


def budget_for(
    seconds: float,
    chars_per_second: float,
    headroom: float = 1.0,
    overhead: float = 0.0,
) -> int:
    """How many characters can be spoken in `seconds`.

    `headroom` above 1.0 allows for the speed-up the voice can still apply on
    top, so the text is not cut further than it has to be. `overhead` is the
    part of an utterance that is not text -- the silence at its edges -- and
    leaving it out makes every budget too generous by that much on every line.
    """
    speakable = seconds * headroom - overhead
    return max(1, int(speakable * chars_per_second))
