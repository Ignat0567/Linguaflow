"""Asking the translation model to shorten what the rules could not.

The rule-based shortener removes filler, and machine-translated prose has very
little of it: measured on a real 12-minute recording it could touch 19 lines
out of 243, while 101 lines needed a median of 11% taken off to be speakable
in the time they had. Removing 11% of a sentence without changing what it says
is rewriting, and no table of phrases rewrites.

So this hands the remaining lines to the same model that did the translating,
with the budget for each. It runs only when the user is already in online
mode, because it sends the text to the same third party the translation went
to and no further -- and never in offline mode, where "nothing leaves this
computer" is a promise rather than a default.

Everything that comes back is checked before it is used. A shortened line that
lost a figure, gained or lost a negation, grew instead of shrinking, or came
back empty is discarded and the original kept: running over is a smaller fault
than saying something else.
"""

from __future__ import annotations

from dataclasses import dataclass

from .condense import Condensed, _safe, budgets_for


@dataclass
class ShortenReport:
    """What the model was asked, and what survived the checks."""

    asked: int = 0
    accepted: int = 0
    rejected_unsafe: int = 0
    rejected_longer: int = 0
    failed: str = ""

    @property
    def used(self) -> bool:
        return self.asked > 0

    def summary(self) -> str:
        if self.failed:
            return f"Сокращение моделью не выполнено: {self.failed}"
        if not self.asked:
            return ""
        text = f"модель сократила {self.accepted} из {self.asked}"
        refused = self.rejected_unsafe + self.rejected_longer
        if refused:
            text += f", {refused} отклонено проверкой"
        return text


def can_shorten(provider: object) -> bool:
    """Whether this provider is one that can rewrite, rather than translate."""
    return callable(getattr(provider, "shorten", None))


def shorten_cues(
    cues,
    language: str,
    chars_per_second: float,
    provider,
    headroom: float = 1.0,
    overhead: float = 0.0,
    measure=None,
    records: list[Condensed] | None = None,
) -> tuple[list, list[Condensed], ShortenReport]:
    """Shorten the lines that still do not fit, using the model.

    `records` is the rule-based pass's own record, extended in place so that
    one line's history reads as one entry however many steps it took.
    """
    from dataclasses import replace

    from ..subtitles.cues import CueStyle, _wrap

    report = ShortenReport()
    cues = list(cues)
    records = list(records) if records else [
        Condensed(text=cue.flat_text, original=cue.flat_text) for cue in cues
    ]
    style = CueStyle.for_language(language)

    budgets = budgets_for(cues, chars_per_second, headroom, overhead, measure)
    pending: list[tuple[int, str, int]] = []
    for index, cue in enumerate(cues):
        text = cue.flat_text
        if text.strip() and len(text) > budgets[index]:
            pending.append((index, text, budgets[index]))

    if not pending:
        return cues, records, report

    report.asked = len(pending)
    try:
        answers = provider.shorten([(text, budget) for _, text, budget in pending],
                                   language)
    except Exception as error:  # noqa: BLE001 -- the dub proceeds unshortened
        report.failed = str(error)
        return cues, records, report

    for (index, original, budget), answer in zip(pending, answers):
        candidate = (answer or "").strip()
        if not candidate or len(candidate) >= len(original):
            report.rejected_longer += 1
            continue
        if not _safe(original, candidate, language):
            report.rejected_unsafe += 1
            continue
        report.accepted += 1
        cues[index] = replace(cues[index], lines=_wrap(candidate, style))
        records[index].text = candidate
        records[index].steps.append("сокращено моделью")

    return cues, records, report
