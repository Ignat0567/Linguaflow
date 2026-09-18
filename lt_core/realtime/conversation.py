"""Two people, two languages, one microphone.

Conversation mode translates in both directions at once: whatever A says goes
to B's language, whatever B says goes to A's. The difficulty is that a single
microphone does not say who is speaking.

Whisper already reports which language it heard, and in a two-language
conversation that answer is the speaker label. It costs nothing extra and it is
the one signal that is actually reliable here -- far more so than trying to
tell two voices apart, which needs speaker diarisation, a second model, and
several seconds of audio before it can decide anything.

The cost is that it cannot separate two people speaking the same language.
That is not this mode: two people sharing a language have no need of a
translator between them.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from .. import languages
from ..asr.transcriber import Transcriber
from ..audio.types import AudioChunk
from ..mt.translator import Translator
from .session import BALANCED, LiveSession, LiveUpdate, Pace

_SENTENCE_END = re.compile(r"[.!?…。！？]['\"»”’)\]]*\s*$")
#: The same marks, found anywhere rather than only at the end, so a sentence
#: that finished in the middle of a commit is read out now instead of waiting
#: for a later commit to land exactly on a full stop.
_SENTENCE_BREAK = re.compile(r"[.!?…。！？]['\"»”’)\]]*(?=\s|$)")
_CLAUSE_BREAK = re.compile(r"[,;:—–、，；：](?=\s|$)")

#: How many words one side may run on for without finishing a sentence before
#: part of it is translated anyway. A turn normally ends at a handover, which
#: releases it; this is for somebody who holds the floor and never stops.
MAX_HELD_WORDS = 60

def _last_break(text: str, pattern: re.Pattern[str] = _SENTENCE_BREAK) -> int:
    """Where the last complete sentence in `text` ends, or 0 if none does."""
    last = None
    for match in pattern.finditer(text):
        last = match
    return last.end() if last else 0


_SCRIPTS = {
    "cyrillic": re.compile(r"[Ѐ-ӿ]"),
    "latin": re.compile(r"[A-Za-zÀ-ÿ]"),
    "han": re.compile(r"[぀-ヿ一-鿿]"),
}

#: How far one alphabet must outnumber the other before the text is called for
#: it. Russian carries "31%", "API" and "$12,000" without becoming English.
SCRIPT_MAJORITY = 3


def _script_of(text: str) -> str | None:
    """Which alphabet this text is written in, if one of them clearly wins."""
    counts = {name: len(pattern.findall(text)) for name, pattern in _SCRIPTS.items()}
    best = max(counts, key=lambda name: counts[name])
    if not counts[best]:
        return None
    rest = sum(count for name, count in counts.items() if name != best)
    return best if counts[best] >= max(1, SCRIPT_MAJORITY * rest) else None


def _script_for_language(code: str) -> str | None:
    """The alphabet a language is written in, read off its own sample text."""
    return _script_of(languages.punctuation_sample(code))


@dataclass
class Side:
    """One participant: the language they speak and the one they read."""

    language: str
    label: str

    def __str__(self) -> str:
        return self.label


class ConversationSession:
    """Alternating two-way translation over one audio stream.

    Runs one recogniser over the audio and routes each utterance by the
    language it turned out to be in. Two independent sessions would each
    transcribe every word, doubling the work to reach the same answer.
    """

    def __init__(
        self,
        transcriber: Transcriber,
        translator: Translator,
        left: Side,
        right: Side,
        pace: Pace = BALANCED,
    ) -> None:
        if left.language == right.language:
            raise ValueError(
                "В режиме «Разговор» у собеседников должны быть разные языки: "
                f"оба выбрали {left.language}."
            )
        self.left = left
        self.right = right
        self.translator = translator

        # Language detection runs per window, because the speaker changes.
        # Everywhere else it is pinned after the first pass; here that would
        # translate the whole conversation as if one person were talking.
        self._session = LiveSession(
            transcriber,
            translator=None,          # translation is routed here, not there
            source_language=left.language,
            target_language=None,
            pace=pace,
            use_prompt=False,
        )
        self.transcriber = transcriber
        self._history: list[LiveUpdate] = []
        self._last_heard: str | None = None
        # Committed words waiting for a sentence to finish. Translating each
        # commit as it lands would hand the model two-word fragments, and a
        # fragment is what makes it invent -- "shipped" came back as
        # "отгруженные", "and thank you" as "И спасибо .".
        self._holding: list[str] = []
        self._holding_for: tuple[str, str] | None = None
        #: Audio since the last tick, used to decide whose turn this is.
        self._recent: np.ndarray | None = None
        self._previous_speaker: str | None = None
        self._unclear = 0
        #: The last provisional translation and the text it was made from, so
        #: a sentence that has not grown is not translated again.
        self._preview: tuple[str, str] = ("", "")
        self._left_script = _script_for_language(left.language)
        self._right_script = _script_for_language(right.language)

    @property
    def stats(self):
        return self._session.stats

    @property
    def history(self) -> list[LiveUpdate]:
        return list(self._history)

    def _route(self, language: str) -> tuple[Side, Side] | None:
        if language == self.left.language:
            return self.left, self.right
        if language == self.right.language:
            return self.right, self.left
        return None

    def feed(self, chunk: AudioChunk) -> list[LiveUpdate]:
        self._recent = (
            chunk.samples if self._recent is None
            else np.concatenate([self._recent, chunk.samples])
        )

        update = self._session.feed(chunk)
        if update is None:
            return []

        heard = self._decide_language()
        self._recent = None

        if heard and self._last_heard and heard != self._last_heard:
            # The other person started talking. Close the previous turn before
            # its tail gets glued onto the new speaker's opening words --
            # agreement knows nothing about whose voice it is listening to.
            tail = self._session.agreement.flush()
            if tail:
                update = LiveUpdate(
                    committed=(
                        update.committed + " " + "".join(w.text for w in tail)
                    ).strip(),
                    partial="",
                    speaker=update.speaker,
                    audio_time=update.audio_time,
                    latency=update.latency,
                )
        if heard:
            self._last_heard = heard

        if not update.committed:
            # Provisional text still belongs on screen, on the side of whoever
            # was last speaking, so the panel does not jump about.
            return [LiveUpdate(
                partial=update.partial,
                speaker=self._history[-1].speaker if self._history else None,
                audio_time=update.audio_time,
                latency=update.latency,
            )]

        spoken = self._by_script(update.committed) or heard
        route = self._route(spoken) if spoken else None
        if route is None:
            # A language neither participant speaks. Show it untranslated
            # rather than guessing a direction and translating into the wrong
            # one.
            resolved = LiveUpdate(
                committed=update.committed,
                partial=update.partial,
                speaker=None,
                audio_time=update.audio_time,
                latency=update.latency,
            )
            self._history.append(resolved)
            return [resolved]

        speaker, listener = route
        released, translation, provisional = self._hold(
            update.committed, speaker.language, listener.language
        )

        produced: list[LiveUpdate] = []
        if released:
            # The previous speaker's unfinished sentence, closed by the
            # handover. It belongs to them, not to whoever is talking now --
            # attaching it to the current update put Russian text under an
            # English speaker's name.
            produced.append(LiveUpdate(
                translation=released,
                speaker=self._previous_speaker,
                audio_time=update.audio_time,
            ))

        resolved = LiveUpdate(
            committed=update.committed,
            partial=update.partial,
            translation=translation,
            partial_translation=provisional,
            speaker=speaker.label,
            audio_time=update.audio_time,
            latency=update.latency,
        )
        self._previous_speaker = speaker.label
        produced.append(resolved)
        self._history.extend(produced)
        return produced

    def _by_script(self, text: str) -> str | None:
        """Whose language this text is written in, when the two sides do not
        share an alphabet.

        Which window the audio fell in is a guess about who was speaking. Which
        alphabet the words came out in is not a guess. Committed text trails
        the audio by a few seconds, so at a handover the window has already
        changed hands while the text still belongs to whoever was talking --
        measured on a two-language dialogue, "four major features." was handed
        to the Russian side and "За последние три месяца." to the English one,
        and both came back from the translator unchanged, because asking it to
        put English into English is asking for nothing.

        Silent where the two sides share an alphabet, which is where the
        question is genuinely hard and the audio is all there is.
        """
        if self._left_script is None or self._left_script == self._right_script:
            return None
        found = _script_of(text)
        if found == self._left_script:
            return self.left.language
        if found == self._right_script:
            return self.right.language
        return None

    #: How much better the other language must score before the turn switches.
    #: Detection is decisive on clean speech -- measured at 0.99 and above on
    #: one-second windows -- so a window that comes back undecided is one that
    #: straddles the handover, and keeping the current speaker is the better
    #: guess there.
    SWITCH_MARGIN = 0.5
    #: Below this, a window is not evidence of anything.
    CONFIDENT = 0.3
    #: Consecutive unclear windows before concluding neither side is speaking.
    UNCLEAR_LIMIT = 3

    def _decide_language(self) -> str | None:
        """Which of the two participants this window belongs to.

        Restricted to the pair rather than open to all ninety-nine languages:
        "which of these two" is a far easier question, and a window containing
        neither scores near zero for both, which is itself useful information.
        """
        if self._recent is None or self._recent.size < 8000:
            return self._last_heard

        best, score, margin = self.transcriber.detect_between(
            self._recent, [self.left.language, self.right.language]
        )

        if not best or score < self.CONFIDENT:
            # A window can score low because it holds a third language, or
            # simply because it holds a breath between two phrases. Measured on
            # the reference dialogue, a pause in the middle of an English turn
            # scored "ru 0.21" -- and treating that as a speaker change
            # relabelled the sentence around it.
            #
            # So one weak window changes nothing. Only a run of them is taken
            # as evidence that neither participant is speaking.
            self._unclear += 1
            if self._unclear < self.UNCLEAR_LIMIT:
                return self._last_heard
            return None

        self._unclear = 0
        if best != self._last_heard and margin < self.SWITCH_MARGIN:
            return self._last_heard
        self._session.source_language = best
        return best

    def _hold(
        self, text: str, source: str, target: str
    ) -> tuple[str, str, str]:
        """Accumulate committed text; translate once a sentence is complete.

        A turn change also releases it: whatever the previous speaker left
        unfinished will never be finished, and holding it back would mean
        translating it into the wrong direction on the next turn.

        Returns what the previous turn left, what has settled now, and a
        provisional reading of the sentence still being spoken. The last of
        those is what keeps the other person able to follow: asking only
        whether the accumulation ends on a full stop made one measured turn
        wait sixteen seconds to be translated at all.
        """
        pair = (source, target)
        released = ""
        if self._holding and self._holding_for and self._holding_for != pair:
            released = self._flush_holding()

        self._holding.append(text)
        self._holding_for = pair
        combined = " ".join(self._holding).strip()

        cut = _last_break(combined)
        if cut <= 0 and len(combined.split()) > MAX_HELD_WORDS:
            cut = _last_break(combined, _CLAUSE_BREAK)
        settled = ""
        if cut > 0:
            settled = self._say(combined[:cut].strip(), source, target)
            combined = combined[cut:].strip()
            self._holding = [combined] if combined else []
            if not combined:
                self._holding_for = None

        return released, settled, self._provisional(combined, source, target)

    def _provisional(self, text: str, source: str, target: str) -> str:
        """The sentence still being spoken, translated as it stands.

        Replaced on the next tick and superseded by the settled translation,
        which is the same contract the original text already has. Held back
        from the history, because provisional text is not a record of anything.
        """
        if not text:
            self._preview = ("", "")
            return ""
        if text == self._preview[0]:
            return self._preview[1]
        answer = self._say(text, source, target)
        self._preview = (text, answer)
        return answer

    def _say(self, text: str, source: str, target: str) -> str:
        if not text:
            return ""
        try:
            results, _ = self.translator.translate([text], source, target)
        except Exception:  # noqa: BLE001 -- one turn, not the conversation
            return ""
        return results[0] if results else ""

    def _flush_holding(self) -> str:
        if not self._holding or self._holding_for is None:
            return ""
        text = " ".join(self._holding).strip()
        source, target = self._holding_for
        self._holding = []
        self._holding_for = None
        self._preview = ("", "")
        return self._say(text, source, target)

    def run(self, chunks: Iterator[AudioChunk]) -> Iterator[LiveUpdate]:
        for chunk in chunks:
            for update in self.feed(chunk):
                if update.has_content:
                    yield update
        final = self._session.finish()
        leftover_speaker = self._previous_speaker
        leftover = self._flush_holding()
        if not final.committed and leftover:
            yield LiveUpdate(translation=leftover, speaker=leftover_speaker,
                             audio_time=final.audio_time)
        if final.committed:
            heard = self._session.source_language
            route = self._route(heard) if heard else None
            if route is not None:
                speaker, listener = route
                self._holding.append(final.committed)
                self._holding_for = (speaker.language, listener.language)
                final = LiveUpdate(
                    committed=final.committed,
                    translation=" ".join(
                        part for part in (leftover, self._flush_holding()) if part
                    ),
                    speaker=speaker.label,
                    audio_time=final.audio_time,
                )
            self._history.append(final)
            yield final
