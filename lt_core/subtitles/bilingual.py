"""Subtitles carrying both languages.

Translation replaces the text of a cue and leaves its timing alone: the words
were spoken when they were spoken, whatever language they are written in.

Bilingual cues stack the translation above the original, because the reader
needs the translation first and the original as a check. Four lines is more
than the two-line rule allows, which is the price of the format -- a bilingual
subtitle is a study aid, not broadcast output, and anyone using one has
accepted that trade.
"""

from __future__ import annotations

import re

from ..subtitles.cues import _CLINGING_WORDS, Cue, CueStyle, _wrap

_ENDS_SENTENCE = re.compile(r"[.!?…。！？]['\"»”’)\]］】」』]*$")


#: The longest run of cues translated as one unit, in words.
#:
#: Forty, because that is the largest piece the translator hands the model in
#: any case: a longer input is cut into forty-word pieces before it is read
#: (see lt_core.mt.nllb.MAX_WORDS). Grouping to the same size therefore changes
#: nothing about what the model is asked to translate, and everything about
#: where the answer is put back.
MAX_GROUP_WORDS = 40


def group_into_sentences(
    cues: tuple[Cue, ...], max_words: int = MAX_GROUP_WORDS
) -> list[list[int]]:
    """Group consecutive cues that together make one sentence.

    Translating a cue on its own translates a fragment, and NLLB answers a
    fragment with an invention. Measured on one-word inputs: "Yes." came back
    as "Нет, нет." -- the opposite -- and "Hello." as "Ich hab's dir gesagt."
    Given whole sentences the same model is accurate.

    Cues are cut for reading speed, not for grammar, so one sentence routinely
    spans two or three of them. Grouping by sentence gives the model something
    it can actually translate, and the timings are untouched: only the text is
    redistributed afterwards.

    A group is also closed once it reaches `max_words`, which matters only when
    no sentence end arrives -- and none does whenever the recogniser stops
    punctuating, which it does for minutes at a time. Measured on a 21-minute
    recording: one "sentence" of 106 cues, eight thousand characters of speech
    with no full stop anywhere in it. Its translation is put back across those
    cues in proportion to their length, and nothing re-anchors that split, so
    an error on the third cue is still there on the ninetieth. Measured on a
    276-cue recording with its sentence ends removed, against the same cues
    grouped by sentence: the translation ran a median of 7.4 seconds away from
    the speech under it, 23.5 at worst, with 234 of 276 cues more than two
    seconds out of step. Capped at forty words: a median of zero, 7.5 at worst,
    47 cues out of step.
    """
    groups: list[list[int]] = []
    current: list[int] = []
    length = 0
    for position, cue in enumerate(cues):
        words = len(cue.flat_text.split())
        if current and length + words > max_words:
            groups.append(current)
            current, length = [], 0
        current.append(position)
        length += words
        if _ENDS_SENTENCE.search(cue.flat_text.strip()):
            groups.append(current)
            current, length = [], 0
    if current:
        groups.append(current)
    return groups


#: How far a proportional split may move to land on a boundary a reader would
#: choose.
#:
#: Two words. Enough to step off a preposition or onto a comma, small enough
#: that the text stays in step with the speech under it -- at an ordinary pace
#: two words is about half a second.
NUDGE = 2

#: A unit that ends a clause is the best place to cut: the reader is already
#: pausing there.
_ENDS_CLAUSE = re.compile(r"[,;:—–]$")


def _cut_near(units: list[str], consumed: int, wanted: int, most: int) -> int:
    """Move a proportional split onto a boundary, if one is close enough.

    Splitting purely by proportion puts cue boundaries wherever the arithmetic
    lands, and the arithmetic knows nothing about phrases. Measured on an hour
    of real output: 42 of 1462 Russian cues ended on a word that governs the
    next one -- "...масса это количество людей, умноженное на" and then, a cue
    later, "энергию". The source language has been avoiding this since Day 2;
    its translation had not.

    A clause end wins over anything, because the reader is already pausing
    there. Failing that, anything but a word left dangling from what it
    governs. Failing both, the proportional point stands -- a boundary that
    cannot be improved is better than text that has drifted from its speech.
    """
    options = sorted(
        (candidate for candidate in range(wanted - NUDGE, wanted + NUDGE + 1)
         if 1 <= candidate <= most),
        key=lambda candidate: (abs(candidate - wanted), candidate),
    )
    if not options:
        return wanted

    for acceptable in (
        lambda unit: bool(_ENDS_CLAUSE.search(unit)),
        lambda unit: unit.strip(_TRAILING).casefold() not in _CLINGING_WORDS,
    ):
        for candidate in options:
            if acceptable(units[consumed + candidate - 1].strip()):
                return candidate
    return wanted


#: Punctuation to look past when asking what word this is.
_TRAILING = ".,!?;:»\"'()[]…—–"


def distribute(text: str, weights: list[int], join_with_space: bool = True) -> list[str]:
    """Split translated text across cues in proportion to their source length.

    An approximation, and openly so: word order differs between languages, so
    there is no exact mapping from a translated sentence back onto the cues its
    source occupied. Splitting at word boundaries nearest the proportional
    point keeps each cue roughly in step with the speech under it, which is
    what a reader needs, and never loses a word, which is what matters more.
    """
    total = sum(weights) or 1
    if len(weights) == 1:
        return [text]

    units = text.split(" ") if join_with_space else list(text)
    joiner = " " if join_with_space else ""
    if len(units) <= len(weights):
        # Fewer words than cues: give each cue at most one and pad the rest.
        return [
            units[position] if position < len(units) else ""
            for position in range(len(weights))
        ]

    parts: list[str] = []
    consumed = 0
    for position, weight in enumerate(weights):
        if position == len(weights) - 1:
            parts.append(joiner.join(units[consumed:]))
            break
        share = weight / total
        wanted = max(1, round(share * len(units)))
        # Leave at least one unit for every cue still to come.
        remaining_cues = len(weights) - position - 1
        most = len(units) - consumed - remaining_cues
        wanted = min(wanted, most)
        if join_with_space:
            wanted = _cut_near(units, consumed, wanted, most)
        parts.append(joiner.join(units[consumed:consumed + wanted]))
        consumed += wanted
    return parts


def translate_cues(
    cues: tuple[Cue, ...], translations: list[str], style: CueStyle | None = None
) -> tuple[Cue, ...]:
    """Replace each cue's text, keeping its timing exactly.

    The lists are matched by position, so a length mismatch means the alignment
    is already broken and every cue after it would carry someone else's words.
    """
    if len(translations) != len(cues):
        raise ValueError(
            f"{len(translations)} переводов на {len(cues)} субтитров — "
            f"соответствие нарушено."
        )
    style = style or CueStyle()
    built: list[Cue] = []
    for cue, text in zip(cues, translations):
        cleaned = text.strip()
        if not cleaned:
            # An empty share means the sentence's words were used up on
            # earlier cues, not that this cue should fall back to the
            # source language. Measured on a German lecture: "Das ist
            # eine schlechte Bewegung." became four one-word cues, the
            # Russian had three words, and the fourth cue stayed
            # "Bewegung." -- German in a Russian subtitle file.
            if built:
                prev = built[-1]
                built[-1] = Cue(
                    prev.index, prev.start, max(prev.end, cue.end), prev.lines
                )
            else:
                built.append(Cue(
                    index=len(built) + 1, start=cue.start, end=cue.end,
                    lines=cue.lines,
                ))
            continue
        built.append(Cue(
            index=len(built) + 1,
            start=cue.start,
            end=cue.end,
            lines=_wrap(cleaned, style),
        ))
    return tuple(built)


def fold_original(
    original: tuple[Cue, ...], translated: tuple[Cue, ...]
) -> tuple[Cue, ...]:
    """Merge source cues so they share the translated list's timings.

    Empty translation shares are absorbed into the previous cue, so the
    translated list can be shorter. Bilingual output still needs one original
    per translated cue; leftovers fold into the cue that ate their time.
    """
    folded: list[Cue] = []
    position = 0
    for target in translated:
        chunk: list[str] = []
        while position < len(original) and original[position].start < target.end - 1e-4:
            if original[position].end > target.start + 1e-4:
                text = original[position].flat_text.strip()
                if text:
                    chunk.append(text)
            position += 1
        folded.append(
            Cue(
                index=target.index,
                start=target.start,
                end=target.end,
                lines=((" ".join(chunk),) if chunk else ("",)),
            )
        )
    if position < len(original) and folded:
        extra = " ".join(
            cue.flat_text.strip() for cue in original[position:] if cue.flat_text.strip()
        )
        if extra:
            last = folded[-1]
            text = f"{last.flat_text} {extra}".strip()
            folded[-1] = Cue(
                last.index, last.start, max(last.end, original[-1].end), (text,)
            )
    return tuple(folded)


def merge_bilingual(
    original: tuple[Cue, ...],
    translated: tuple[Cue, ...],
    translation_first: bool = True,
) -> tuple[Cue, ...]:
    """One cue per timing, holding both languages."""
    if not translated:
        raise ValueError(
            f"{len(original)} и {len(translated)} субтитров — "
            f"их нельзя совместить."
        )
    if len(original) != len(translated):
        original = fold_original(original, translated)
    if len(original) != len(translated):
        raise ValueError(
            f"{len(original)} и {len(translated)} субтитров — "
            f"их нельзя совместить."
        )
    merged = []
    for source, target in zip(original, translated):
        lines = (
            (*target.lines, *source.lines)
            if translation_first
            else (*source.lines, *target.lines)
        )
        merged.append(
            Cue(index=source.index, start=source.start, end=source.end, lines=lines)
        )
    return tuple(merged)
