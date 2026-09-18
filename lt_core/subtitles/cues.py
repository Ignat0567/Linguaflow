"""Turning a transcript into subtitles people can actually read.

Whisper produces segments up to thirty seconds long. Written straight to an SRT
they are not subtitles -- a wall of text that appears, sits for half a minute
and vanishes. Real subtitles obey constraints that have nothing to do with
speech recognition: how fast a person reads, how many characters fit on a line,
how long a cue must stay up to be noticed at all.

The numbers here follow broadcast practice (Netflix and BBC guidelines agree
closely): about 42 Latin characters per line, two lines, 17 characters per
second of reading speed, a minimum of roughly 5/6 of a second on screen.

Chinese and Japanese need their own numbers, not a translation of these. A
Chinese character carries far more than a Latin one, so the line limit is
lower, the reading speed is counted in characters rather than letters, and
nothing is joined with spaces. Applying Latin rules to them produces cues that
are simultaneously too wide and too brief.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .. import languages
from ..asr.types import Segment, Transcript, Word


def _writes_without_spaces(language: str) -> bool:
    """Chinese and Japanese put no spaces between words.

    Read from the catalogue rather than hard-coded, so a language added there
    brings its own answer with it.
    """
    entry = languages.get(language)
    return bool(entry and entry.scriptio_continua)


# Strong break: a sentence ended here, so a cue may end here at no cost.
_SENTENCE_END = re.compile(r"[.!?…。！？]['\"»”’)\]]*$")
# Weak break: a clause ended. Better than splitting mid-phrase, worse than a
# sentence boundary.
_CLAUSE_END = re.compile(r"[,;:、，；：)\]]['\"»”’]*$")

# One unit that must never be divided: a run of digits and Latin letters (a
# number, a percentage, an embedded English word), a single CJK character, or a
# punctuation mark.
_CJK_TOKEN = re.compile(r"[0-9A-Za-z][0-9A-Za-z.,:%\-]*|\s+|.", re.UNICODE)
# Punctuation a line may end on. Tested against the end of a unit rather than
# the whole of it: punctuation is glued to the character before it, so a unit
# reads "す。" rather than "。" on its own.
_CJK_ENDS_WITH_PUNCT = re.compile(r"[、。，！？；：,.!?;:]$")

# Words that belong with what follows them. Ending a cue on one separates it
# from the phrase it introduces, which reads as a stumble. Covers the six
# space-separated languages in scope; Chinese and Japanese break by character
# count and never reach this path.
_CLINGING_WORDS = {
    # en
    "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "with", "from",
    "and", "or", "but", "as", "per", "into", "over", "under", "about",
    # de
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "und", "oder", "aber", "von", "zu", "mit", "für", "auf", "über", "durch",
    # ru
    "и", "или", "но", "в", "во", "на", "с", "со", "к", "ко", "по", "за", "из",
    "от", "до", "для", "при", "о", "об", "под", "над", "через",
    # es
    "el", "la", "los", "las", "un", "una", "de", "del", "y", "o", "pero", "en",
    "con", "por", "para", "sin", "sobre",
    # it
    "il", "lo", "gli", "un", "uno", "una", "e", "ed", "ma", "di", "da", "su",
    "tra", "fra", "nel", "nella",
    # fr
    "le", "les", "une", "des", "du", "et", "ou", "mais", "dans", "sur", "sous",
    "avec", "sans", "pour", "chez", "vers",
}


@dataclass(frozen=True)
class CueStyle:
    max_chars_per_line: int = 42
    max_lines: int = 2
    # Characters per second of reading time. Exceeding it means the cue is gone
    # before it has been read.
    max_cps: float = 17.0
    min_duration: float = 0.85
    max_duration: float = 7.0
    # Two frames at 25 fps. Without a gap, consecutive cues look like one cue
    # that flickers.
    min_gap: float = 0.08
    join_with_space: bool = True
    # A silence at least this long is treated as a real boundary in the speech.
    # Shorter gaps are within a phrase and must not end a cue.
    pause_break: float = 0.40

    @property
    def max_chars(self) -> int:
        return self.max_chars_per_line * self.max_lines

    @classmethod
    def for_language(cls, language: str) -> "CueStyle":
        if _writes_without_spaces(language):
            # A Chinese line of 42 characters is roughly three times the
            # content of a Latin one and takes far longer to read.
            return cls(
                max_chars_per_line=16,
                max_lines=2,
                max_cps=9.0,
                join_with_space=False,
            )
        return cls()


@dataclass(frozen=True)
class Cue:
    index: int
    start: float
    end: float
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def flat_text(self) -> str:
        return " ".join(self.lines)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def chars_per_second(self) -> float:
        characters = sum(len(line) for line in self.lines)
        return characters / self.duration if self.duration > 0 else float("inf")


def build_cues(
    transcript: Transcript, style: CueStyle | None = None
) -> tuple[Cue, ...]:
    """Split a transcript into readable, correctly timed cues."""
    style = style or CueStyle.for_language(transcript.language)

    groups: list[tuple[list[Word], Segment]] = []
    for run, segment in _speech_runs(transcript, style):
        if run:
            for chunk in _split_words(run, style):
                groups.append((chunk, segment))
        else:
            # No word timings: the segment has to travel as one cue, however
            # long it is. Better a long cue than a cue timed by guesswork.
            groups.append(([], segment))

    cues: list[Cue] = []
    for position, (words, segment) in enumerate(groups, start=1):
        if words:
            text = _join(words, style)
            start, end = words[0].start, words[-1].end
        else:
            text, start, end = segment.text, segment.start, segment.end
        cues.append(
            Cue(index=position, start=start, end=end, lines=_wrap(text, style))
        )

    return tuple(_fix_timing(_merge_runts(cues, style), style))


# -- splitting -----------------------------------------------------------

def _speech_runs(
    transcript: Transcript, style: CueStyle
) -> list[tuple[list[Word], Segment]]:
    """Group words into continuous runs of speech, ignoring segment borders.

    Whisper's segments are cut by its thirty-second decoding window, not by the
    speaker. On the Day 2 reference clip five of eight segment boundaries fell
    mid-phrase -- segments ending on "per", "our", "of", "a", "the" -- with a
    gap of exactly 0.00 s to the next, which is to say no pause at all.
    Treating those as cue boundaries stamps every one of them into the
    subtitles.

    So words are read as one stream and divided where the audio actually goes
    quiet. A segment carrying no word timings cannot join a run and is passed
    through on its own.
    """
    runs: list[tuple[list[Word], Segment]] = []
    current: list[Word] = []
    owner: Segment | None = None

    for segment in transcript.segments:
        if not segment.words:
            if current and owner is not None:
                runs.append((current, owner))
                current, owner = [], None
            runs.append(([], segment))
            continue

        if owner is None:
            owner = segment
        for word in segment.words:
            if current and word.start - current[-1].end >= style.pause_break:
                runs.append((current, owner))
                current, owner = [], segment
            current.append(word)

    if current and owner is not None:
        runs.append((current, owner))
    return runs


def _split_words(words: list[Word], style: CueStyle) -> list[list[Word]]:
    """Divide a segment's words into cue-sized runs.

    Breaks at a sentence end wherever one is available, at a clause end
    otherwise, and only mid-phrase when nothing else will fit.
    """
    runs: list[list[Word]] = []
    current: list[Word] = []

    for word in words:
        candidate = current + [word]
        if current and not _fits(candidate, style):
            # This word will not fit. Prefer to have broken earlier, at a
            # punctuation mark, rather than exactly at the overflow point.
            split_at = _best_break(current, style)
            runs.append(current[:split_at])
            current = current[split_at:] + [word]
            continue

        current = candidate
        # A sentence ended and the run is already substantial: stop here rather
        # than gluing the next sentence on.
        if _SENTENCE_END.search(word.text.strip()) and _long_enough(current, style):
            runs.append(current)
            current = []

    if current:
        runs.append(current)
    return [run for run in runs if run]


def _fits(words: list[Word], style: CueStyle) -> bool:
    text = _join(words, style)
    if len(text) > style.max_chars:
        return False
    if words[-1].end - words[0].start > style.max_duration:
        return False
    return True


def _long_enough(words: list[Word], style: CueStyle) -> bool:
    """Is this run worth ending, or is it a fragment like "Yes."?

    A one-word cue followed by a long one reads worse than a single combined
    cue, so very short runs are allowed to absorb what comes next.
    """
    return len(_join(words, style)) >= style.max_chars_per_line // 2


def _glued(words: list[Word], position: int, style: CueStyle) -> bool:
    """Would a cut here fall inside a word rather than between two?

    Whisper emits "self-improvement" as " self" and "-improvement,", the second
    with no leading space, and `_join` puts them back together. The absence of
    that space is the only thing that says they are one word -- so a cue
    boundary between them is a cue boundary inside a word, and the viewer reads
    "...to commit to a policy of self" followed by "-improvement, self-change."
    Numbers break the same way: "$12" and ",000".
    """
    if not style.join_with_space or not 0 < position < len(words):
        return False
    return not words[position].text[:1].isspace()


def _best_break(words: list[Word], style: CueStyle) -> int:
    """Index to cut at, searching backwards for the most natural boundary."""
    # Do not strand a lone word at either end of the split.
    lowest = max(1, len(words) // 3)
    for pattern in (_SENTENCE_END, _CLAUSE_END):
        for position in range(len(words) - 1, lowest - 1, -1):
            if (
                pattern.search(words[position - 1].text.strip())
                and not _glued(words, position, style)
            ):
                return position

    # No punctuation to break on. Avoid stranding a preposition, article or
    # conjunction at the end of a cue, separated from what it governs: "...by
    # roughly $12,000 per / month" reads as a stumble. Stepping back one word
    # keeps the phrase together.
    for position in range(len(words) - 1, lowest - 1, -1):
        if (
            words[position - 1].text.strip().lower() not in _CLINGING_WORDS
            and not _glued(words, position, style)
        ):
            return position
    return len(words)


# -- text shaping --------------------------------------------------------

def _join(words: list[Word], style: CueStyle) -> str:
    """Reassemble words, honouring the spacing the model gave them.

    Whisper's tokens carry their own leading whitespace, and its absence is
    meaningful: "$12" is followed by ",000" and "real" by "-time", neither with
    a space. Stripping the tokens and re-joining with a uniform space turns
    those into "$12 ,000" and "real -time" -- corrupted numbers and broken
    hyphenation in every export.
    """
    if style.join_with_space:
        return "".join(word.text for word in words).strip()
    return "".join(word.text.strip() for word in words)


def _wrap(text: str, style: CueStyle) -> tuple[str, ...]:
    """Break a cue's text into balanced lines.

    Balanced rather than greedy: a 40/4 split looks broken, 22/22 does not.
    """
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= style.max_chars_per_line:
        return (text,)

    if not style.join_with_space:
        return _wrap_without_spaces(text, style)

    words = text.split(" ")
    best: tuple[str, ...] | None = None
    best_score = None
    # Try every split point and keep the most even one that fits.
    for cut in range(1, len(words)):
        first = " ".join(words[:cut])
        second = " ".join(words[cut:])
        if len(first) > style.max_chars_per_line:
            break
        if len(second) > style.max_chars_per_line:
            continue
        score = abs(len(first) - len(second))
        if best_score is None or score < best_score:
            best, best_score = (first, second), score

    if best is not None:
        return best

    # Nothing fits in two lines. This happens constantly on translated cues:
    # Russian runs 15-20% longer than English, German longer still, so a cue
    # laid out for the source language overflows in the target. Words are never
    # dropped to make it fit -- that would change what was said -- so the cue
    # takes a third line.
    #
    # Balanced across however many lines are needed, not filled greedily: a
    # greedy fill leaves the remainder stranded on the last line, which is how
    # a three-line cue ends with one short word on its own.
    # How many lines this actually needs has to be discovered by packing, not
    # by dividing the length: word boundaries decide it. A 78-character line
    # with a 14-character word in the wrong place needs three lines even though
    # 78 divided by 42 says two.
    needed = len(_pack(words, style.max_chars_per_line))
    return _pack(words, style.max_chars_per_line, target=len(text) / needed)


def _pack(words: list[str], width: int, target: float | None = None) -> tuple[str, ...]:
    """Fill lines up to `width`, breaking early to approach `target`."""
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        too_wide = len(candidate) > width
        # Breaking early at the target keeps the last line from being a stub.
        past_target = (
            target is not None
            and len(line) >= target * 0.7
            and abs(len(line) - target) <= abs(len(candidate) - target)
        )
        if line and (too_wide or past_target):
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return tuple(lines)


def _wrap_without_spaces(text: str, style: CueStyle) -> tuple[str, ...]:
    """Line-break Chinese and Japanese.

    Slicing every N characters is wrong in two ways that both showed up
    immediately. It splits numbers -- "31%" became "3" at the end of one line
    and "1%" at the start of the next -- and it leaves absurd balances, a full
    line followed by three characters.

    So the text is first cut into units that must not be divided: a run of
    digits and Latin letters is one unit, each CJK character is its own, and
    punctuation stays with what precedes it. Lines are then balanced across
    those units, preferring a break after punctuation where there is one.

    Without a word segmenter a break can still fall inside a two-character
    word. That is a real limitation, and a much smaller one than splitting a
    number in half.
    """
    units = _atomic_units(text)
    width = style.max_chars_per_line
    total = sum(len(unit) for unit in units)

    if total <= width:
        return (text,)

    lines: list[str] = []
    remaining = units
    while remaining:
        length = sum(len(unit) for unit in remaining)
        if length <= width:
            lines.append("".join(remaining))
            break
        # Aim for equal lines rather than filling each to the brim: 16/3 is a
        # worse read than 10/9 for the same content.
        lines_left = -(-length // width)
        cut = _cut_near(remaining, width, target=length / lines_left)
        lines.append("".join(remaining[:cut]))
        remaining = remaining[cut:]
    return tuple(lines)


def _atomic_units(text: str) -> list[str]:
    units: list[str] = []
    for token in _CJK_TOKEN.finditer(text):
        piece = token.group(0)
        # Trailing punctuation belongs to the unit before it, never alone at
        # the start of a line.
        if units and _CJK_ENDS_WITH_PUNCT.fullmatch(piece):
            units[-1] += piece
        else:
            units.append(piece)
    return units


def _cut_near(units: list[str], width: int, target: float) -> int:
    """Units to put on this line: as close to `target` as the limits allow.

    A punctuation boundary wins over a purely arithmetic one when it is
    anywhere near the target, because a line that ends on a comma reads as a
    deliberate break rather than an accident.
    """
    used = 0
    widest = 0
    lengths: list[int] = []
    for position, unit in enumerate(units):
        used += len(unit)
        lengths.append(used)
        if used <= width:
            widest = position + 1
    widest = max(1, widest)

    punctuated = [
        position for position in range(1, widest + 1)
        if _CJK_ENDS_WITH_PUNCT.search(units[position - 1])
        and lengths[position - 1] >= width // 3
    ]
    if punctuated:
        return min(punctuated, key=lambda p: abs(lengths[p - 1] - target))

    balanced = min(
        range(1, widest + 1), key=lambda p: abs(lengths[p - 1] - target)
    )
    return balanced


# -- merging -------------------------------------------------------------

def _merge_runts(cues: list[Cue], style: CueStyle) -> list[Cue]:
    """Absorb cues too small to deserve their own appearance.

    A pause of half a second is a real pause, and splitting on it is correct --
    but it can leave a fragment like "Guten Morgen," alone on screen for the
    minimum duration while the sentence it belongs to follows separately. Two
    flashes read worse than one cue, so a runt joins its neighbour whenever the
    result still fits the line, duration and reading-speed limits.

    Only across short gaps: a long silence is a genuine break, and bridging it
    would put a subtitle on screen well before the words are spoken.
    """
    merged: list[Cue] = []
    position = 0
    runt_chars = style.max_chars_per_line // 2

    while position < len(cues):
        cue = cues[position]
        following = cues[position + 1] if position + 1 < len(cues) else None
        characters = sum(len(line) for line in cue.lines)

        if following is not None and characters < runt_chars:
            joiner = " " if style.join_with_space else ""
            combined_text = cue.flat_text + joiner + following.flat_text
            combined_end = following.end
            duration = combined_end - cue.start
            fits = (
                len(combined_text) <= style.max_chars
                and duration <= style.max_duration
                and following.start - cue.end <= 1.0
                and (style.max_cps <= 0 or len(combined_text) / duration <= style.max_cps)
            )
            if fits:
                merged.append(
                    Cue(index=len(merged) + 1, start=cue.start, end=combined_end,
                        lines=_wrap(combined_text, style))
                )
                position += 2
                continue

        merged.append(
            Cue(index=len(merged) + 1, start=cue.start, end=cue.end, lines=cue.lines)
        )
        position += 1
    return merged


# -- timing --------------------------------------------------------------

def _fix_timing(cues: list[Cue], style: CueStyle) -> list[Cue]:
    """Enforce minimum duration, reading speed and inter-cue gaps.

    Cues are extended into the silence that follows them where there is any,
    because a cue that is too short to read is worse than one that lingers.
    Nothing is extended into the next cue's start.
    """
    fixed: list[Cue] = []
    for position, cue in enumerate(cues):
        start, end = cue.start, cue.end
        characters = sum(len(line) for line in cue.lines)

        wanted = max(
            style.min_duration,
            characters / style.max_cps if style.max_cps > 0 else 0.0,
        )
        limit = (
            cues[position + 1].start - style.min_gap
            if position + 1 < len(cues)
            else end + wanted
        )
        if end - start < wanted:
            end = min(max(end, start + wanted), max(limit, end))

        # Never overlap the cue before it.
        if fixed and start < fixed[-1].end + style.min_gap:
            start = min(fixed[-1].end + style.min_gap, end - 0.01)

        fixed.append(
            Cue(index=len(fixed) + 1, start=start, end=max(end, start + 0.05),
                lines=cue.lines)
        )
    return fixed
