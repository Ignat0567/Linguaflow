"""Terms that must not be translated, or must be translated one particular way.

Product names, people, companies, internal jargon. A model will happily render
"Sentinel" as "Wachposten" and "Alex" as "Александр", and in a business
recording that is worse than leaving them in English.

The mechanism is deliberately not the placeholder substitution that was tried
for numbers and measured not to work (see lt_core.mt.numbers). Instead the
translated text is repaired afterwards: whatever the model produced for a
protected term is replaced with the term the user asked for. Repair is possible
here and impossible for numbers, because a glossary says what the right answer
is, and no such table exists for arbitrary arithmetic.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Glossary:
    """Source term -> per-language replacement.

    An empty replacement means "leave the source term as it is", which is the
    common case for names and product identifiers.
    """

    entries: dict[str, dict[str, str]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entries)

    def add(self, term: str, translations: dict[str, str] | None = None) -> None:
        self.entries[term] = dict(translations or {})

    def wanted(self, term: str, language: str) -> str:
        return self.entries.get(term, {}).get(language) or term

    def terms_in(self, text: str) -> list[str]:
        """Which glossary terms the source text actually contains.

        Longest first, so "Acme Corporation" wins over "Acme". Word-boundary
        matched for Latin scripts; a bare substring search would rewrite
        "Alexandra" while trying to protect "Alex".
        """
        found = []
        for term in sorted(self.entries, key=len, reverse=True):
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE):
                found.append(term)
        return found

    def apply(self, source: str, translated: str, language: str) -> str:
        """Force the wanted rendering of every term present in the source.

        Only terms actually in the source are considered, so a glossary of two
        hundred entries costs nothing on a line that contains none of them.
        """
        for term in self.terms_in(source):
            wanted = self.wanted(term, language)
            if wanted.lower() in translated.lower():
                continue
            translated = _replace_best_candidate(translated, term, wanted)
        return translated

    # -- loading ---------------------------------------------------------
    @classmethod
    def load(cls, path: Path | str) -> "Glossary":
        """Read a glossary from CSV or JSON.

        CSV: first column the source term, remaining columns named by language
        code in the header row. JSON: {"term": {"de": "...", "ru": "..."}}.
        """
        target = Path(path)
        if not target.exists():
            raise FileNotFoundError(f"Глоссарий не найден: {target}")

        if target.suffix.lower() == ".json":
            payload = json.loads(target.read_text(encoding="utf-8"))
            return cls(entries={
                term: dict(values) if isinstance(values, dict) else {}
                for term, values in payload.items()
            })

        glossary = cls()
        with target.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return glossary
            key = reader.fieldnames[0]
            for row in reader:
                term = (row.get(key) or "").strip()
                if not term:
                    continue
                glossary.add(term, {
                    name: (value or "").strip()
                    for name, value in row.items()
                    if name != key and (value or "").strip()
                })
        return glossary


def _replace_best_candidate(translated: str, term: str, wanted: str) -> str:
    """Put `wanted` where the model's rendering of `term` went.

    Without alignment there is no way to know which word that was. A token of
    similar length starting with the same letter is a reasonable guess for a
    transliterated name; when nothing resembles it, the term is appended in
    brackets rather than silently dropped, so a reviewer can see what happened.
    """
    tokens = re.findall(r"\w+", translated, re.UNICODE)
    initial = term[:1].lower()
    candidates = [
        token for token in tokens
        if token[:1].lower() == initial and abs(len(token) - len(term)) <= 3
    ]
    if candidates:
        best = max(candidates, key=len)
        return re.sub(rf"(?<!\w){re.escape(best)}(?!\w)", wanted, translated, count=1)
    return f"{translated} [{wanted}]"
