"""The translation layer the rest of the program talks to.

Picks a provider according to the user's explicit choice of mode, caches
repeated lines, applies the glossary, and audits the numbers afterwards.

The mode is never inferred and never falls back on its own. "Offline" is a
promise that nothing leaves this machine; quietly reaching for a cloud service
when the local model fails would break that promise at exactly the moment it
mattered most -- a confidential negotiation, a medical consultation. If the
offline path cannot do the job, it says so.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

RISKY_WORD_COUNT = 2

#: Below this share of the original's length, a translation is reported as
#: cut off rather than accepted.
#:
#: Among the languages offered, a translation is never much shorter than its
#: original -- Russian runs longer than English, German longer still, and the
#: shortest real pair measured stayed above 0.8. So half is not a judgement
#: about style; it is far below anything a working translation produces, and
#: it is what a truncated one looks like.
#:
#: Measured on a real file: a 6752-character run came back as 1025 characters,
#: cut off mid-clause, with nothing anywhere saying so. The model had simply
#: stopped writing at its own ceiling. That silence is what this catches.
SHORT_RATIO = 0.5
"""Inputs of this many words or fewer cannot be trusted from a local model.

NLLB was trained heavily on subtitle corpora, where a short line is a dialogue
turn. Given one in isolation it produces a plausible turn rather than a
translation. Measured, English to Russian and German:

    "Yes."    -> "Нет, нет."              (the opposite)
    "Hello."  -> "Ich hab's dir gesagt."  (unrelated)

Most cues escape this because whole sentences are sent rather than fragments
(see lt_core.subtitles.bilingual), but a genuinely one-word utterance is still
a one-word input. It cannot be fixed downstream, so it is flagged instead: a
reviewer checking four lines is in a far better position than one trusting two
hundred.
"""

from .. import languages
from .glossary import Glossary
from .numbers import NumberMismatch, audit
from .types import TranslationError, TranslationMode, TranslationProvider


@dataclass
class TranslationReport:
    """What happened, in terms a reviewer can act on."""

    provider: str
    offline: bool
    source_language: str
    target_language: str
    count: int
    elapsed: float
    number_mismatches: list[NumberMismatch] = field(default_factory=list)
    empty_results: list[int] = field(default_factory=list)
    # Inputs too short for the model to be trusted on. See RISKY_WORD_COUNT.
    risky_short: list[int] = field(default_factory=list)
    # Translations far shorter than what they were made from. See SHORT_RATIO.
    truncated: list[int] = field(default_factory=list)
    cache_hits: int = 0

    @property
    def needs_review(self) -> bool:
        return bool(
            self.number_mismatches or self.empty_results
            or self.risky_short or self.truncated
        )

    def summary(self) -> str:
        parts = [
            f"{self.count} фрагментов через {self.provider} "
            f"за {self.elapsed:.1f} с"
        ]
        if self.cache_hits:
            parts.append(f"{self.cache_hits} из кэша")
        if self.number_mismatches:
            parts.append(f"ЧИСЛА РАСХОДЯТСЯ в {len(self.number_mismatches)}")
        if self.empty_results:
            parts.append(f"пустой перевод в {len(self.empty_results)}")
        if self.risky_short:
            parts.append(
                f"{len(self.risky_short)} слишком коротких для надёжного перевода"
            )
        if self.truncated:
            parts.append(
                f"ПЕРЕВОД ОБОРВАН в {len(self.truncated)} — текст короче оригинала "
                "более чем вдвое"
            )
        return ", ".join(parts)


class Translator:
    """Front end over one provider, with the safeguards applied around it."""

    def __init__(
        self,
        provider: TranslationProvider,
        glossary: Glossary | None = None,
        check_numbers: bool = True,
    ) -> None:
        self.provider = provider
        self.glossary = glossary or Glossary()
        self.check_numbers = check_numbers
        self._cache: dict[tuple[str, str, str], str] = {}

    @property
    def mode(self) -> str:
        return TranslationMode.OFFLINE if self.provider.is_offline else TranslationMode.ONLINE

    def translate(
        self, texts: list[str], source: str, target: str
    ) -> tuple[list[str], TranslationReport]:
        """Translate a batch, returning results and a report on them."""
        if source == target:
            raise TranslationError(
                f"Язык оригинала и перевода совпадают ({source})."
            )
        if not self.provider.supports(source, target):
            raise TranslationError(
                f"{self.provider.name} не поддерживает пару {source} → {target}."
            )

        started = time.perf_counter()
        results: list[str | None] = [None] * len(texts)
        pending: list[str] = []
        pending_positions: list[int] = []
        hits = 0

        # Deduplicate within the batch as well as against the cache. A lecture
        # repeats stock phrases; a subtitle file repeats them more, because one
        # sentence often spans several cues. Without this, identical lines are
        # translated once per occurrence -- correct, and wasteful in proportion
        # to how repetitive the speaker is.
        queued: dict[str, int] = {}
        for position, text in enumerate(texts):
            stripped = text.strip()
            if not stripped:
                results[position] = ""
                continue
            key = (stripped, source, target)
            if key in self._cache:
                results[position] = self._cache[key]
                hits += 1
            elif stripped in queued:
                hits += 1
            else:
                queued[stripped] = len(pending)
                pending.append(stripped)
                pending_positions.append(position)

        if pending:
            translated = self.provider.translate(pending, source, target)
            if len(translated) != len(pending):
                # Results are matched to subtitle timings by position, so a
                # provider returning a different count would silently shift
                # every line after the discrepancy onto the wrong timestamp.
                raise TranslationError(
                    f"{self.provider.name} вернул {len(translated)} переводов "
                    f"на {len(pending)} запросов — соответствие нарушено."
                )
            for source_text, output in zip(pending, translated):
                self._cache[(source_text, source, target)] = self.glossary.apply(
                    source_text, output, target
                )

        # Fill every position from the cache, including the duplicates that
        # were never sent.
        for position, text in enumerate(texts):
            if results[position] is not None:
                continue
            results[position] = self._cache.get((text.strip(), source, target), "")

        final = [result or "" for result in results]
        report = TranslationReport(
            provider=self.provider.name,
            offline=self.provider.is_offline,
            source_language=source,
            target_language=target,
            count=len(texts),
            elapsed=time.perf_counter() - started,
            cache_hits=hits,
            empty_results=[
                position for position, (src, out) in enumerate(zip(texts, final))
                if src.strip() and not out.strip()
            ],
            risky_short=[
                position for position, src in enumerate(texts)
                if src.strip() and len(src.split()) <= RISKY_WORD_COUNT
                and getattr(self.provider, "unreliable_on_short_input", False)
            ],
        )
        report.truncated = [
            position for position, (src, out) in enumerate(zip(texts, final))
            if _looks_cut_off(src, out, target)
        ]
        if self.check_numbers:
            report.number_mismatches = audit(texts, final)
        return final, report


def _looks_cut_off(source: str, output: str, target: str) -> bool:
    """Whether a translation is too short to be the whole of its original.

    Only applied to inputs long enough for the ratio to mean anything: over a
    handful of words the length relationship between these languages is
    stable, under it a legitimate translation can be a single word.
    """
    source, output = source.strip(), output.strip()
    if not source or not output or len(source.split()) < 12:
        return False
    if not languages.joins_with_space(target):
        # Chinese and Japanese genuinely say the same thing in far fewer
        # characters, so the ratio here means something else entirely.
        return False
    return len(output) < len(source) * SHORT_RATIO


def build_translator(
    mode: str,
    glossary_path: Path | str | None = None,
    model_root: Path | str | None = None,
    **provider_options,
) -> Translator:
    """Construct the translator for the mode the user chose.

    Raises rather than substituting a different mode. A user who asked for
    offline and silently got a cloud call has been misled about where their
    words went.
    """
    glossary = Glossary.load(glossary_path) if glossary_path else Glossary()

    if mode == TranslationMode.OFFLINE:
        from .nllb import NllbTranslator

        return Translator(
            NllbTranslator(model_root=model_root, **provider_options), glossary
        )

    if mode == TranslationMode.ONLINE:
        from .cloud import build_cloud_provider

        return Translator(build_cloud_provider(**provider_options), glossary)

    raise TranslationError(
        f"Неизвестный режим перевода «{mode}». "
        f"Доступны: {TranslationMode.OFFLINE}, {TranslationMode.ONLINE}."
    )
