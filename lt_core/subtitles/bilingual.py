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

from ..subtitles.cues import Cue, CueStyle, _wrap

_ENDS_SENTENCE = re.compile(r"[.!?…。！？]['\"»”’)\]］】」』]*$")


def group_into_sentences(cues: tuple[Cue, ...]) -> list[list[int]]:
    """Group consecutive cues that together make one sentence.

    Translating a cue on its own translates a fragment, and NLLB answers a
    fragment with an invention. Measured on one-word inputs: "Yes." came back
    as "Нет, нет." -- the opposite -- and "Hello." as "Ich hab's dir gesagt."
    Given whole sentences the same model is accurate.

    Cues are cut for reading speed, not for grammar, so one sentence routinely
    spans two or three of them. Grouping by sentence gives the model something
    it can actually translate, and the timings are untouched: only the text is
    redistributed afterwards.
    """
    groups: list[list[int]] = []
    current: list[int] = []
    for position, cue in enumerate(cues):
        current.append(position)
        if _ENDS_SENTENCE.search(cue.flat_text.strip()):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


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
        wanted = min(wanted, len(units) - consumed - remaining_cues)
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
    return tuple(
        Cue(
            index=cue.index,
            start=cue.start,
            end=cue.end,
            lines=_wrap(text.strip(), style) if text.strip() else cue.lines,
        )
        for cue, text in zip(cues, translations)
    )


def merge_bilingual(
    original: tuple[Cue, ...],
    translated: tuple[Cue, ...],
    translation_first: bool = True,
) -> tuple[Cue, ...]:
    """One cue per timing, holding both languages."""
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
