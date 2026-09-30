"""Checking that numbers survived translation.

The Day 0 spike found NLLB turning "twelve thousand dollars" into 12万美元 --
a hundred and twenty thousand, a factor of ten out, on a financial figure, in
fluent Chinese that gives no hint anything went wrong.

The obvious defence is to hide numbers behind placeholders and put them back
afterwards. That was measured and it does not work: of seven placeholder
formats tried across seven target languages, the best survived five, and the
two it failed on were Chinese and Japanese -- precisely where the corruption
happens. The model rewrites or drops anything that does not look like language.

So numbers travel unprotected and are audited afterwards. Digits fare much
better than spelled-out numerals, and Whisper already normalises "four hundred
and twenty" to "420", so most of the input arrives in the safer form. What
remains is caught here:

    en -> zh   "4.7 million dollars"          -> 47万美元      (470,000)
    en -> ja   "420 milliseconds to 290"      -> 290秒         (unit changed)

Auditing cannot fix a mistranslation, and pretending otherwise would be worse
than useless. What it does is turn two hundred cues nobody can check into five
cues somebody can.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# CJK scale characters, largest first so longer chains parse correctly.
_CJK_SCALES: list[tuple[str, Decimal]] = [
    ("兆", Decimal(10) ** 12),
    ("億", Decimal(10) ** 8),
    ("亿", Decimal(10) ** 8),
    ("万", Decimal(10) ** 4),
    ("萬", Decimal(10) ** 4),
    ("千", Decimal(10) ** 3),
    ("百", Decimal(10) ** 2),
]
_SCALE_CHARS = "".join(scale for scale, _ in _CJK_SCALES)

# A run of digits, possibly with thousands separators and a decimal part.
#
# The lookbehind rejects only a digit or a separator, deliberately not \w.
# Chinese and Japanese put numbers flush against words -- 削减了12,000美元 --
# and \w matches CJK, so a word-boundary guard makes every number in those
# languages invisible. An audit that cannot see the numbers it is auditing is
# worse than no audit, because it reports success.
_NUMBER = re.compile(
    r"(?<![\d.,])"
    r"(\d{1,3}(?:[   ,.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
)

# A CJK numeral chain: 470万, 1万2千 (which is twelve thousand, one number,
# not two), 3億5000万. Each digit group multiplies the scale that follows it
# and the groups are summed.
_CJK_CHAIN = re.compile(
    rf"(?:\d+(?:[.,]\d+)?\s*[{_SCALE_CHARS}]\s*)+\d*(?:[.,]\d+)?"
)
_CJK_PART = re.compile(rf"(\d+(?:[.,]\d+)?)\s*([{_SCALE_CHARS}])?")

# Western scale words, so "4.7 million" compares against 4700000.
#
# Grouped by the value they multiply and written out as whole forms, because
# the languages in scope inflect them. Russian declines a noun through six
# cases in two numbers, and a table of nominative forms is a table that works
# on some sentences and not others: measured on a twelve-minute recording,
# "1.5 million views" came back as "1,5 миллионами просмотров" and was
# reported as a number that had changed -- 1500000 in one text against 1.5 in
# the other -- because the instrumental plural was missing. Six of twelve
# ordinary sentences were flagged the same way.
#
# A warning that cries wolf costs more than no warning at all: the cues it
# flags are precisely the ones a person is asked to stop and check by hand.
#
# Stems with `\w*` after them would be shorter and wrong -- "5 миллионный
# подписчик", the five-millionth subscriber, would read as five million.
_SCALES: dict[str, tuple[str, ...]] = {
    "1000": (
        "thousand", "tausend", "mil", "mille", "mila",
        "тысяча", "тысячи", "тысяче", "тысячу", "тысячей", "тысячью",
        "тысяч", "тысячам", "тысячами", "тысячах",
    ),
    "1000000": (
        "million", "millions", "millionen", "millón", "millones",
        "milione", "milioni",
        "миллион", "миллиона", "миллиону", "миллионом", "миллионе",
        "миллионы", "миллионов", "миллионам", "миллионами", "миллионах",
    ),
    "1000000000": (
        "billion", "billions", "milliarde", "milliarden", "milliard",
        "milliards", "miliardo", "miliardi", "millardo",
        "миллиард", "миллиарда", "миллиарду", "миллиардом", "миллиарде",
        "миллиарды", "миллиардов", "миллиардам", "миллиардами", "миллиардах",
    ),
}
_SCALE_WORDS: dict[str, Decimal] = {
    word: Decimal(value) for value, words in _SCALES.items() for word in words
}
_SCALE_WORD = re.compile(
    r"\b(" + "|".join(sorted(_SCALE_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NumberMismatch:
    index: int
    source: str
    target: str
    missing: tuple[str, ...]
    added: tuple[str, ...]

    def describe(self) -> str:
        parts = []
        if self.missing:
            parts.append(f"пропало: {', '.join(self.missing)}")
        if self.added:
            parts.append(f"появилось: {', '.join(self.added)}")
        return "; ".join(parts)


def _to_decimal(raw: str) -> Decimal | None:
    """Parse a digit run written in any of the separator conventions.

    "12,000" is twelve thousand in English and twelve in German; "12.000" is
    the reverse. The ambiguity is resolved by shape rather than by locale,
    because the locale of a translation is not reliably known: a group of
    exactly three digits after a single separator is a thousands group.
    """
    text = raw.replace(" ", " ").replace(" ", "").replace(" ", "")
    if not text:
        return None

    separators = [c for c in text if c in ".,"]
    try:
        if not separators:
            return Decimal(text)

        last = text.rfind(separators[-1])
        tail = text[last + 1:]
        if len(separators) > 1 or len(tail) == 3:
            # Several separators, or a trailing group of exactly three: the
            # last one is a thousands separator unless a different character
            # was used before it.
            if len(separators) > 1 and separators[-1] != separators[0]:
                return Decimal(text[:last].replace(separators[0], "") + "." + tail)
            return Decimal(re.sub(r"[.,]", "", text))
        return Decimal(text[:last].replace(",", "").replace(".", "") + "." + tail)
    except (InvalidOperation, ValueError):
        return None


_SCALE_LOOKUP = dict(_CJK_SCALES)


def _parse_cjk_chain(chain: str) -> Decimal | None:
    """Sum a CJK numeral chain: 1万2千 is one value, twelve thousand."""
    total = Decimal(0)
    seen = False
    for part in _CJK_PART.finditer(chain):
        value = _to_decimal(part.group(1))
        if value is None:
            continue
        scale = part.group(2)
        total += value * _SCALE_LOOKUP[scale] if scale else value
        seen = True
    return total if seen else None


def extract(text: str) -> list[Decimal]:
    """Every numeric value in the text, in the order it is written.

    Scale words and CJK scale characters are applied, so 4.7 million, 470万 and
    4 700 000 all come back as the same value. Document order does not affect
    the comparison, which is a multiset, but it makes a flagged mismatch
    readable when someone has to look at it.
    """
    found: list[tuple[int, Decimal]] = []
    consumed: list[tuple[int, int]] = []

    # CJK chains first: they span several digit groups that the plain number
    # pattern would otherwise report separately.
    for match in _CJK_CHAIN.finditer(text):
        value = _parse_cjk_chain(match.group(0))
        if value is not None:
            found.append((match.start(), value))
            consumed.append((match.start(), match.end()))

    for match in _NUMBER.finditer(text):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        value = _to_decimal(match.group(1))
        if value is None:
            continue
        # "4.7 million" -- look just past the number for a scale word.
        trailing = text[match.end():match.end() + 16]
        word = _SCALE_WORD.match(trailing.lstrip())
        if word:
            value *= _SCALE_WORDS[word.group(1).lower()]
        found.append((match.start(), value))

    return [value for _, value in sorted(found, key=lambda pair: pair[0])]


def _format(value: Decimal) -> str:
    normalised = value.normalize()
    text = format(normalised, "f")
    return text


def compare(source: str, target: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Values present in one text and not the other.

    Multiset comparison: "from 9 to 2" and "from 2 to 9" both contain the same
    values, and catching a reversal needs more than arithmetic. Catching a
    value that changed, or vanished, needs only this.
    """
    from collections import Counter

    left = Counter(_format(v) for v in extract(source))
    right = Counter(_format(v) for v in extract(target))
    missing = tuple(sorted((left - right).elements()))
    added = tuple(sorted((right - left).elements()))
    return missing, added


def audit(sources: list[str], targets: list[str]) -> list[NumberMismatch]:
    """Find entries whose numbers changed in translation."""
    mismatches: list[NumberMismatch] = []
    for position, (source, target) in enumerate(zip(sources, targets)):
        missing, added = compare(source, target)
        if missing or added:
            mismatches.append(
                NumberMismatch(
                    index=position, source=source, target=target,
                    missing=missing, added=added,
                )
            )
    return mismatches
