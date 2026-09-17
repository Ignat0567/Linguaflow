"""Translation interfaces.

One protocol, several providers. The offline provider runs a model on this
machine; the online providers call a service. Which one is used is the user's
choice and never inferred, because the difference is where their words go.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .. import languages

# Whisper's two-letter codes mapped to the codes NLLB uses, for every language
# in the catalogue -- including those this build does not currently offer, so
# that enabling one needs no change here.
NLLB_CODES: dict[str, str] = {
    code: language.nllb for code, language in languages.CATALOGUE.items()
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
