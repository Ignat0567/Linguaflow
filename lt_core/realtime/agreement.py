"""Deciding when a live transcription can be trusted.

A streaming transcriber re-reads its whole audio buffer on every tick, and its
answer changes as more speech arrives: "I went to the" becomes "I went to the
bank", then "I want to go to the bank". Showing every revision makes the text
twitch; waiting for silence makes it lag by seconds.

LocalAgreement resolves this. A word is committed once two consecutive
hypotheses agree on it -- the model has heard more audio and still says the
same thing. Committed text never changes again, so it can be translated,
spoken aloud, or written to a file. Everything after the agreement point is
shown as provisional and is free to change.

The threshold is two hypotheses rather than three because each extra
confirmation costs a full tick of latency, and the second one already removes
almost all of the churn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..asr.types import Word

# Words are compared on their letters and digits alone. The model punctuates
# inconsistently while a sentence is still arriving -- "bank" one tick, "bank,"
# the next -- and treating that as disagreement would stall the commit for as
# long as the sentence keeps growing.
_COMPARABLE = re.compile(r"[^\w]+", re.UNICODE)


def _key(word: Word) -> str:
    return _COMPARABLE.sub("", word.text).casefold()


@dataclass
class LocalAgreement:
    """Commits words that two consecutive hypotheses agree on."""

    #: Words committed so far, in order. Trimmed by forget_before().
    committed: list[Word] = field(default_factory=list)
    #: The previous hypothesis, beyond the commit point.
    _previous: list[Word] = field(default_factory=list, repr=False)
    #: How far the commit point has advanced, in session seconds.
    #
    # Kept separately from `committed` and never allowed to go backwards.
    # Deriving it from the last committed word would tie it to how much history
    # happens to be retained, so forgetting old words would move the commit
    # point back and let audio already transcribed be accepted a second time.
    _until: float = field(default=0.0, repr=False)

    @property
    def committed_until(self) -> float:
        """End time of the last committed word, in session seconds."""
        return self._until

    @property
    def committed_text(self) -> str:
        return "".join(word.text for word in self.committed).strip()

    def insert(self, hypothesis: list[Word]) -> list[Word]:
        """Feed a fresh hypothesis; get back whatever it newly confirms.

        The hypothesis covers the whole live buffer, including audio that has
        already been committed, so anything ending at or before the commit
        point is dropped before comparison.
        """
        fresh = self._beyond_commit(hypothesis)

        agreed: list[Word] = []
        for index, (current, previous) in enumerate(zip(fresh, self._previous)):
            if _key(current) != _key(previous):
                break
            if not _key(current) and not (index and self._cuts_a_word(fresh, index)):
                # Nothing to compare on: two different marks both reduce to
                # nothing, so "they agree" would mean only that both are
                # punctuation. The exception is a mark glued to the word in
                # front of it -- "%" after " 31", ",000" after " $12" -- which
                # is not a token in its own right but the tail of one that has
                # just agreed.
                break
            # Keep the newer reading: its timing is based on more audio, and
            # its punctuation is more likely to be settled.
            agreed.append(current)

        while agreed and self._cuts_a_word(fresh, len(agreed)):
            agreed.pop()

        if agreed:
            self.committed.extend(agreed)
            self._until = max(self._until, agreed[-1].end)
        self._previous = fresh[len(agreed):]
        return agreed

    @staticmethod
    def _cuts_a_word(words: list[Word], taken: int) -> bool:
        """Whether committing `taken` of these would cut the next one in half.

        Whisper emits "31%" as " 31" and "%", and "$12,000" as " $12" and
        ",000" -- the missing leading space is the only thing that says they
        are one word. Committed text is translated as soon as it settles, so a
        commit that ends on the first half hands the translator a number with
        no unit: measured on a live run, "reduced latency by 31%" was committed
        as "...by 31" and came back as "задержка на 31", and "$12,000 per
        month" became "$1,000 a month".

        The half word waits for its other half, which costs it one tick and
        only when the continuation is already in sight.
        """
        return taken < len(words) and not words[taken].text[:1].isspace()

    def _beyond_commit(self, hypothesis: list[Word]) -> list[Word]:
        """The part of a hypothesis that is not already committed.

        Decided by words, not by the clock. The buffer deliberately keeps a few
        seconds of already-committed audio for context, so a hypothesis opens
        by re-transcribing the tail of what is committed; whatever follows that
        repetition is new.

        Cutting on the commit point instead looks equivalent and is not. The
        model re-estimates every word's boundaries on every pass, so a word
        that was never committed comes back ending a fraction before the commit
        point and disappears -- measured on a real recording, "the people who
        always win" was committed as "the who always win", and "which is the
        ability of these people" as "which is the of these people". The same
        movement the other way commits a word twice: "they They win", "times
        times energy".

        Sometimes there is no repetition to align against: the buffer is
        trimmed after every commit, and on the shorter audio the model does not
        always render the opening again. The word it starts with then is the
        word this agreement was already waiting on, so that is the second
        anchor -- and only when neither matches does the clock decide.
        """
        if not self.committed:
            return list(hypothesis)

        keys = [_key(word) for word in hypothesis]
        tail = [_key(word) for word in self.committed[-len(keys):]]
        for length in range(min(len(tail), len(keys)), 0, -1):
            if tail[-length:] == keys[:length]:
                return list(hypothesis[length:])

        if keys and self._previous and _key(self._previous[0]) == keys[0]:
            # It opens on the word still pending confirmation, so none of it
            # has been committed however its timings happen to read.
            return list(hypothesis)

        return [
            word for word in hypothesis
            if word.end > self.committed_until + 1e-6
        ]

    def pending(self) -> list[Word]:
        """Words seen but not yet confirmed -- the provisional tail."""
        return list(self._previous)

    def pending_text(self) -> str:
        return "".join(word.text for word in self._previous).strip()

    def flush(self) -> list[Word]:
        """Commit the tail unconditionally, at end of session.

        Nothing more is coming, so a second opinion will never arrive. The
        alternative is discarding the last few words of every recording.
        """
        tail = self._previous
        if tail:
            self.committed.extend(tail)
            self._until = max(self._until, tail[-1].end)
        self._previous = []
        return tail

    def force_commit_before(self, moment: float) -> list[Word]:
        """Commit pending words that end before `moment`, without agreement.

        The escape hatch for a word the model will not settle on. Agreement
        only ever confirms a prefix, so a single unstable word blocks
        everything behind it: on the Day 4 reference clip the model rendered
        "31%" differently on every pass and the commit point stood still for
        fourteen seconds while the buffer grew to eighteen.

        Waiting indefinitely for a second opinion that never comes is worse
        than accepting the current one. This is only reached after a stall, and
        only for words far enough from the edge of the buffer that more audio
        is unlikely to change them.
        """
        take = 0
        for word in self._previous:
            if word.end > moment:
                break
            take += 1
        if not take:
            return []

        while take and self._cuts_a_word(self._previous, take):
            take -= 1
        if not take:
            return []

        forced = self._previous[:take]
        self._previous = self._previous[take:]
        self.committed.extend(forced)
        self._until = max(self._until, forced[-1].end)
        return forced

    def forget_before(self, moment: float) -> None:
        """Drop committed words older than `moment`.

        A long session accumulates them indefinitely otherwise: an hour of
        speech is roughly ten thousand Word objects held for no reason, since
        only the recent tail is ever read again.
        """
        self.committed = [
            word for word in self.committed if word.end >= moment
        ]
