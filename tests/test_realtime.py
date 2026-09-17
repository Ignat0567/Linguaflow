"""Day 4: streaming agreement, live sessions, conversation routing."""

from __future__ import annotations

import numpy as np
import pytest

from lt_core.asr.types import Word
from lt_core.audio.types import TARGET_SAMPLE_RATE, AudioChunk
from lt_core.realtime.agreement import LocalAgreement
from lt_core.realtime.conversation import ConversationSession, Side
from lt_core.realtime.session import BALANCED, FAST, STEADY, LiveSession, Pace


def w(text: str, start: float, end: float) -> Word:
    return Word(text=text, start=start, end=end)


def words(*spec) -> list[Word]:
    return [w(text, start, end) for text, start, end in spec]


# -- agreement -----------------------------------------------------------

def test_nothing_commits_on_the_first_hypothesis():
    """There is nothing to agree with yet."""
    agreement = LocalAgreement()
    assert agreement.insert(words((" I", 0, 0.3), (" went", 0.3, 0.6))) == []


def test_agreement_commits_what_two_hypotheses_share():
    agreement = LocalAgreement()
    agreement.insert(words((" I", 0, 0.3), (" went", 0.3, 0.6)))
    committed = agreement.insert(
        words((" I", 0, 0.3), (" went", 0.3, 0.6), (" home", 0.6, 0.9))
    )
    assert [word.text for word in committed] == [" I", " went"]
    assert agreement.pending_text() == "home"


def test_a_revision_stops_the_commit_at_the_disagreement():
    agreement = LocalAgreement()
    agreement.insert(words((" I", 0, 0.3), (" went", 0.3, 0.6), (" out", 0.6, 0.9)))
    committed = agreement.insert(
        words((" I", 0, 0.3), (" want", 0.3, 0.6), (" out", 0.6, 0.9))
    )
    assert [word.text for word in committed] == [" I"]


def test_punctuation_alone_is_not_disagreement():
    """The model punctuates a sentence only once it has finished hearing it.

    Treating "bank" and "bank," as different words would stall the commit for
    as long as the sentence kept growing.
    """
    agreement = LocalAgreement()
    agreement.insert(words((" the", 0, 0.3), (" bank", 0.3, 0.6)))
    committed = agreement.insert(
        words((" the", 0, 0.3), (" bank,", 0.3, 0.6), (" and", 0.6, 0.9))
    )
    assert len(committed) == 2
    assert committed[1].text == " bank,"


def test_committed_audio_is_never_reconsidered():
    agreement = LocalAgreement()
    agreement.insert(words((" one", 0, 0.5), (" two", 0.5, 1.0)))
    agreement.insert(words((" one", 0, 0.5), (" two", 0.5, 1.0)))
    # The model now changes its mind about audio already committed.
    agreement.insert(words((" ONE", 0, 0.5), (" TWO", 0.5, 1.0), (" three", 1.0, 1.5)))
    assert agreement.committed_text == "one two"


def test_flush_takes_the_tail_at_end_of_stream():
    """No further hypothesis is coming, so waiting loses the last words."""
    agreement = LocalAgreement()
    agreement.insert(words((" hello", 0, 0.5), (" there", 0.5, 1.0)))
    assert [word.text for word in agreement.flush()] == [" hello", " there"]
    assert agreement.pending_text() == ""


def test_forced_commit_releases_a_stuck_prefix():
    """One unsettled word otherwise blocks everything behind it.

    Measured on the reference clip: the model rendered "31%" differently on
    every pass and the commit point stood still for fourteen seconds.
    """
    agreement = LocalAgreement()
    agreement.insert(words((" thirty", 0, 0.5), (" one", 0.5, 1.0), (" late", 3.0, 3.5)))
    forced = agreement.force_commit_before(2.0)
    assert [word.text for word in forced] == [" thirty", " one"]
    assert agreement.pending_text() == "late"


def test_forced_commit_leaves_words_near_the_edge_alone():
    agreement = LocalAgreement()
    agreement.insert(words((" recent", 5.0, 5.4)))
    assert agreement.force_commit_before(2.0) == []


def test_forgetting_history_does_not_move_the_commit_point():
    """Regression: deriving the commit point from retained words let audio
    already transcribed be accepted a second time."""
    agreement = LocalAgreement()
    agreement.insert(words((" one", 0, 0.5)))
    agreement.insert(words((" one", 0, 0.5), (" two", 0.5, 1.0)))
    before = agreement.committed_until
    agreement.forget_before(100.0)
    assert agreement.committed == []
    assert agreement.committed_until == before


# -- pacing --------------------------------------------------------------

def test_expected_delay_counts_two_windows():
    """A word cannot be committed on the tick it first appears.

    Agreement needs a second hypothesis, which arrives a window later. An
    earlier version promised one window and was wrong by a whole one.
    """
    pace = Pace(window=2.0)
    assert pace.expected_delay > 2 * pace.window


def test_faster_pace_promises_less_delay():
    assert FAST.expected_delay < BALANCED.expected_delay < STEADY.expected_delay


def test_every_pace_bounds_its_lag():
    for pace in (FAST, BALANCED, STEADY):
        assert pace.max_lag > pace.window
        assert pace.max_buffer > pace.max_lag


# -- live session --------------------------------------------------------

class FakeTranscriber:
    """Returns scripted hypotheses, one per tick."""

    device = "cpu"
    compute_type = "int8"

    def __init__(self, script: list[list[Word]], language: str = "en") -> None:
        self.script = script
        self.language = language
        self.calls = 0
        self.prompts: list[str | None] = []

    def transcribe(self, audio, options=None, on_progress=None, total_duration=None):
        from lt_core.asr.types import Segment, Transcript

        self.prompts.append(getattr(options, "initial_prompt", None))
        index = min(self.calls, len(self.script) - 1)
        self.calls += 1
        hypothesis = self.script[index]
        return Transcript(
            segments=(Segment(text="", start=0.0, end=0.0, words=tuple(hypothesis)),),
            language=self.language,
            language_probability=1.0,
            duration=total_duration or 1.0,
        )


def chunks(seconds: float, size: float = 0.1):
    """A stream of silent chunks with correct session timing."""
    produced = 0.0
    while produced < seconds - 1e-9:
        samples = np.zeros(int(size * TARGET_SAMPLE_RATE), dtype=np.float32)
        yield AudioChunk(samples=samples, start_time=produced)
        produced += size


def test_session_waits_for_a_full_window():
    transcriber = FakeTranscriber([words((" hi", 0, 0.5))])
    session = LiveSession(transcriber, pace=Pace(window=2.0))
    for chunk in chunks(1.0):
        assert session.feed(chunk) is None
    assert transcriber.calls == 0


def test_session_commits_across_ticks():
    script = [
        words((" one", 0.0, 0.5), (" two", 0.5, 1.0)),
        words((" one", 0.0, 0.5), (" two", 0.5, 1.0), (" three", 1.0, 1.5)),
    ]
    session = LiveSession(FakeTranscriber(script), pace=Pace(window=1.0))
    for chunk in chunks(3.0):
        session.feed(chunk)
    assert "one two" in session.agreement.committed_text


def test_session_pins_the_language_it_detected():
    """Re-detecting every tick lets the model change its mind mid-session."""
    transcriber = FakeTranscriber([words((" hi", 0, 0.5))], language="de")
    session = LiveSession(transcriber, pace=Pace(window=1.0))
    for chunk in chunks(2.5):
        session.feed(chunk)
    assert session.source_language == "de"
    assert session.detected_language == "de"


def test_session_feeds_committed_text_back_as_context():
    script = [
        words((" alpha", 0.0, 0.5)),
        words((" alpha", 0.0, 0.5), (" beta", 0.5, 1.0)),
        words((" alpha", 0.0, 0.5), (" beta", 0.5, 1.0), (" gamma", 1.0, 1.5)),
    ]
    transcriber = FakeTranscriber(script)
    session = LiveSession(transcriber, pace=Pace(window=1.0))
    for chunk in chunks(4.0):
        session.feed(chunk)
    assert any(prompt and "alpha" in prompt for prompt in transcriber.prompts)


def test_context_can_be_turned_off():
    """In conversation mode the prompt is in the wrong speaker's language."""
    script = [words((" alpha", 0.0, 0.5))] * 4
    transcriber = FakeTranscriber(script)
    session = LiveSession(transcriber, pace=Pace(window=1.0), use_prompt=False)
    for chunk in chunks(4.0):
        session.feed(chunk)
    assert all(prompt is None for prompt in transcriber.prompts)


def test_buffer_is_bounded_when_nothing_ever_agrees():
    """A model that never repeats itself must not grow the buffer forever."""
    script = [words((f" w{n}", n * 0.4, n * 0.4 + 0.4)) for n in range(40)]
    session = LiveSession(FakeTranscriber(script), pace=Pace(window=1.0, max_lag=3.0))
    for chunk in chunks(20.0):
        session.feed(chunk)
    assert session.stats.max_buffer_seconds < session.pace.max_buffer


def test_stall_is_measured_as_lag_not_as_idle_time():
    """Regression: a single trailing word agreeing reset the stall timer.

    The commit point advanced by hundredths of a second while the stream stood
    still behind it, and the escape hatch almost never fired.
    """
    # One word the model always agrees on, followed by a tail it rewrites
    # every pass. The tail grows, so words that were once at the edge of the
    # buffer end up well behind it -- which is the real situation, and the one
    # the escape hatch exists for.
    stuck = words((" stuck", 0.0, 0.5))
    script = [
        stuck + [w(f" v{tick}_{i}", 1.0 + i * 0.5, 1.5 + i * 0.5)
                 for i in range(tick + 1)]
        for tick in range(20)
    ]
    session = LiveSession(FakeTranscriber(script), pace=Pace(window=1.0, max_lag=3.0))
    for chunk in chunks(15.0):
        session.feed(chunk)
    assert session.stats.forced_commits > 0
    assert session.agreement.committed_until > 1.0, "the stream must move on"


# -- conversation --------------------------------------------------------

def test_conversation_requires_two_different_languages():
    with pytest.raises(ValueError, match="разные языки"):
        ConversationSession(
            FakeTranscriber([]), None, Side("en", "A"), Side("en", "B")
        )


def test_conversation_routes_each_side_to_the_other():
    session = ConversationSession.__new__(ConversationSession)
    session.left = Side("en", "A")
    session.right = Side("ru", "B")
    assert session._route("en") == (session.left, session.right)
    assert session._route("ru") == (session.right, session.left)
    assert session._route("de") is None


def test_held_text_waits_for_a_finished_sentence():
    """A fragment is what makes the model invent: "shipped" came back as
    "отгруженные"."""
    session = ConversationSession.__new__(ConversationSession)
    session._holding = []
    session._holding_for = None
    session.translator = _EchoTranslator()

    released, translation = session._hold("We cut", "en", "ru")
    assert released == "" and translation == ""
    released, translation = session._hold("spending sharply.", "en", "ru")
    assert translation == "[ru] We cut spending sharply."


def test_a_turn_change_releases_the_unfinished_sentence():
    """It will never be finished, and holding it would translate it into the
    next speaker's direction."""
    session = ConversationSession.__new__(ConversationSession)
    session._holding = []
    session._holding_for = None
    session.translator = _EchoTranslator()

    session._hold("An unfinished thought", "en", "ru")
    released, _ = session._hold("Ответ.", "ru", "en")
    assert released == "[ru] An unfinished thought"


class _EchoTranslator:
    def translate(self, texts, source, target):
        return [f"[{target}] {text}" for text in texts], None
