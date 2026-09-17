"""Translation interfaces.

One protocol, several providers. The offline provider runs a model on this
machine; the online providers call a service. Which one is used is the user's
choice and never inferred, because the difference is where their words go.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Whisper's two-letter codes mapped to the codes NLLB uses. The script matters:
# NLLB distinguishes rus_Cyrl from rus_Latn, and zho_Hans from zho_Hant.
NLLB_CODES: dict[str, str] = {
    "en": "eng_Latn",
    "de": "deu_Latn",
    "ru": "rus_Cyrl",
    "zh": "zho_Hans",
    "ja": "jpn_Jpan",
    "es": "spa_Latn",
    "it": "ita_Latn",
    "fr": "fra_Latn",
}


class TranslationError(RuntimeError):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


@dataclass(frozen=True)
class TranslationMode:
    """How the user wants translating done.

    Explicit rather than automatic. "Offline" is a promise that nothing leaves
    the machine, and a silent fallback to a cloud service would break that
    promise at exactly the moment it mattered -- a confidential call, a medical
    consultation. If the offline path fails, it fails loudly.
    """

    OFFLINE = "offline"
    ONLINE = "online"


@dataclass
class TranslationResult:
    texts: tuple[str, ...]
    source_language: str
    target_language: str
    provider: str
    elapsed: float = 0.0
    # Segments the provider returned empty or unchanged. Not an error on its
    # own -- "OK" translates to "OK" -- but a run where most entries land here
    # means something is wrong upstream.
    suspicious: tuple[int, ...] = field(default=())


@runtime_checkable
class TranslationProvider(Protocol):
    """What every backend must offer."""

    name: str
    is_offline: bool

    def translate(
        self, texts: list[str], source: str, target: str
    ) -> list[str]:
        """Translate each entry, returning one output per input, in order.

        Length and order are part of the contract: callers align the results
        against subtitle timings by position.
        """

    def supports(self, source: str, target: str) -> bool:
        ...
