"""Day 4: streaming agreement, live sessions, conversation routing."""

from __future__ import annotations

import numpy as np
import pytest

from lt_core.asr.types import Word
from lt_core.audio.types import TARGET_SAMPLE_RATE, AudioChunk
from lt_core.realtime.agreement import LocalAgreement
from lt_core.realtime.conversation import ConversationSession, Side
from lt_core.tts.casting import FEMALE, MALE
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


def test_a_word_is_not_lost_when_its_timing_drifts_across_the_commit_point():
    """Measured on a real recording: "the people who always win the game" came
    out committed as "the who always win the game".

    The timings are the measured ones. "the" is committed, ending at 3.84; the
    buffer is trimmed and the model re-reads the shorter audio, where the word
    after it now ends at 3.80 -- four hundredths before the commit point, and
    so filtered out as though it had already been committed. It had not: it was
    the word this agreement was waiting to confirm.
    """
    agreement = LocalAgreement()
    agreement.insert(words((" the", 3.70, 3.84)))
    agreement.insert(words((" the", 3.72, 3.84), (" people", 3.84, 4.36),
                           (" who", 4.36, 4.62)))
    assert agreement.committed_text == "the"

    agreement.insert(words((" people", 2.68, 3.80), (" who", 3.80, 4.60),
                           (" always", 4.60, 5.44)))
    assert agreement.committed_text == "the people who"


def test_a_word_is_not_committed_twice_when_its_timing_drifts_the_other_way():
    """The same movement in the other direction produced "they They win" and
    "times times energy"."""
    agreement = LocalAgreement()
    agreement.insert(words((" they", 7.38, 7.94)))
    agreement.insert(words((" they", 7.38, 7.94), (" win", 7.94, 8.34)))
    assert agreement.committed_text == "they"
    agreement.insert(words((" they", 7.36, 7.96), (" win", 7.96, 8.34)))
    agreement.insert(words((" they", 7.36, 7.98), (" win", 7.98, 8.36),
                           (" because", 8.36, 8.86)))
    assert agreement.committed_text == "they win"


def test_a_commit_never_ends_on_half_a_number():
    """Measured on a live run: "reduced latency by 31%" was committed as
    "...by 31" and translated straight away, because committed text is
    translated as soon as it settles. It came back as "задержка на 31".

    Whisper emits "31%" as " 31" and "%", and the missing leading space is the
    only thing that says they are one word. The first hypothesis says
    " percent.", the second says "%", so agreement rightly stops between them
    -- and must not hand over the half it has.
    """
    agreement = LocalAgreement()
    agreement.insert(words((" by", 1.0, 1.2), (" 31", 1.2, 1.6),
                           (" percent.", 1.6, 2.2)))
    committed = agreement.insert(words((" by", 1.0, 1.2), (" 31", 1.2, 1.6),
                                       ("%", 1.6, 1.8), (" and", 1.8, 2.0)))
    assert [w.text for w in committed] == [" by"]
    assert agreement.committed_text == "by"


def test_the_two_halves_commit_together_once_both_are_agreed():
    agreement = LocalAgreement()
    agreement.insert(words((" by", 1.0, 1.2), (" 31", 1.2, 1.6), ("%", 1.6, 1.8)))
    agreement.insert(words((" by", 1.0, 1.2), (" 31", 1.2, 1.6), ("%", 1.6, 1.8),
                           (" and", 1.8, 2.0)))
    assert agreement.committed_text == "by 31%"


def test_a_forced_commit_does_not_cut_a_word_either():
    """The escape hatch for a word the model will not settle on must not
    become a way to hand over half of one."""
    agreement = LocalAgreement()
    agreement.insert(words((" costs", 0.0, 0.5), (" $12", 0.5, 1.0),
                           (",000", 1.0, 1.4)))
    forced = agreement.force_commit_before(2.0)
    assert [w.text for w in forced] == [" costs", " $12", ",000"]

    agreement = LocalAgreement()
    agreement.insert(words((" costs", 0.0, 0.5), (" $12", 0.5, 1.0),
                           (",000", 1.4, 1.8)))
    forced = agreement.force_commit_before(1.2)
    assert [w.text for w in forced] == [" costs"], (
        "it stopped before the continuation and kept the first half"
    )


def test_the_end_of_a_session_still_takes_everything():
    """No further hypothesis is coming, so half a word is all there will ever
    be of it -- and dropping it would lose the figure outright."""
    agreement = LocalAgreement()
    agreement.insert(words((" costs", 0.0, 0.5), (" $12", 0.5, 1.0),
                           (",000", 1.0, 1.4)))
    tail = agreement.flush()
    assert "".join(w.text for w in tail).strip() == "costs $12,000"


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


class _EchoTranslator:
    def translate(self, texts, source, target):
        return [f"[{target}] {text}" for text in texts], None


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


def test_the_previous_speakers_words_can_be_kept_out_of_the_prompt():
    """In conversation mode the committed text is in the other person's
    language, and carrying it forward drags the model into transcribing the
    next speaker in it too -- measured, a German turn came out as Russian."""
    script = [words((" alpha", 0.0, 0.5))] * 4
    transcriber = FakeTranscriber(script)
    session = LiveSession(transcriber, source_language="en",
                          pace=Pace(window=1.0), carry_context=False)
    for chunk in chunks(4.0):
        session.feed(chunk)
    assert all(prompt is None or "alpha" not in prompt
               for prompt in transcriber.prompts)


def test_the_punctuated_example_is_sent_even_without_context():
    """It is not anybody's words -- it is what a finished sentence looks like,
    and without one this model transcribes speech as an unbroken run. A live
    sentence with no full stop in it is a turn nobody can read."""
    from lt_core import languages

    script = [words((" alpha", 0.0, 0.5))] * 4
    transcriber = FakeTranscriber(script)
    session = LiveSession(transcriber, source_language="de",
                          pace=Pace(window=1.0), carry_context=False)
    for chunk in chunks(4.0):
        session.feed(chunk)
    sample = languages.punctuation_sample("de")
    assert sample
    assert any(prompt == sample for prompt in transcriber.prompts)


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


def test_a_finished_sentence_is_translated_without_waiting_for_the_next_one():
    """It used to ask whether the whole accumulation ended on a full stop, so a
    sentence that finished mid-commit waited for a later commit to land exactly
    on one. Measured on a five-minute talk: the first translation appeared at
    40 s, they arrived a median of 10 s apart, and one was 496 characters."""
    script = [
        words((" Hello.", 0.0, 0.5), (" How", 0.5, 1.0)),
        words((" Hello.", 0.0, 0.5), (" How", 0.5, 1.0), (" are", 1.0, 1.5)),
    ]
    session = LiveSession(
        FakeTranscriber(script), translator=_EchoTranslator(),
        source_language="en", target_language="ru", pace=Pace(window=1.0),
    )
    settled = [
        update.translation
        for update in (session.feed(chunk) for chunk in chunks(3.0))
        if update and update.translation
    ]
    assert settled, "a finished sentence was never translated"
    assert "Hello." in settled[0]
    assert "How" not in settled[0], "the unfinished tail went with it"


def test_the_sentence_still_being_spoken_is_translated_provisionally():
    """Waiting for a full stop is right for text that will never be revised,
    and on its own it leaves a reader with nothing while a long sentence is
    spoken."""
    script = [
        words((" The", 0.0, 0.5), (" cat", 0.5, 1.0)),
        words((" The", 0.0, 0.5), (" cat", 0.5, 1.0), (" sat", 1.0, 1.5)),
    ]
    session = LiveSession(
        FakeTranscriber(script), translator=_EchoTranslator(),
        source_language="en", target_language="ru", pace=Pace(window=1.0),
    )
    previews = [
        update.partial_translation
        for update in (session.feed(chunk) for chunk in chunks(3.0))
        if update and update.partial_translation
    ]
    assert previews, "nothing was offered while the sentence was unfinished"
    assert "The cat" in previews[-1]


def test_the_provisional_translation_gives_way_to_the_committed_one():
    """Two translations of the same words on screen at once is worse than a
    short delay."""
    script = [
        words((" The", 0.0, 0.5), (" cat", 0.5, 1.0)),
        words((" The", 0.0, 0.5), (" cat", 0.5, 1.0), (" sat.", 1.0, 1.5)),
        words((" The", 0.0, 0.5), (" cat", 0.5, 1.0), (" sat.", 1.0, 1.5),
              (" Then", 1.5, 2.0)),
    ]
    session = LiveSession(
        FakeTranscriber(script), translator=_EchoTranslator(),
        source_language="en", target_language="ru", pace=Pace(window=1.0),
    )
    for chunk in chunks(4.0):
        update = session.feed(chunk)
        if update and update.translation:
            assert not update.partial_translation, (
                "the settled translation arrived with a draft of itself"
            )


def test_a_sentence_that_never_ends_is_committed_at_a_clause():
    """A speaker who runs clause into clause without a full stop must not stop
    the translation altogether. Broken at a comma, never mid-phrase."""
    run = words(*[(f" word{n}", n * 1.0, n * 1.0 + 1.0) for n in range(40)])
    run[9] = w(" nine,", 9.0, 10.0)
    session = LiveSession(
        FakeTranscriber([run, run]), translator=_EchoTranslator(),
        source_language="en", target_language="ru", pace=Pace(window=1.0),
    )
    settled = [
        update.translation
        for update in (session.feed(chunk) for chunk in chunks(45.0))
        if update and update.translation
    ]
    assert settled, "nothing was committed for a speaker who never stops"
    assert settled[0].rstrip().endswith("nine,"), settled[0]


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


def test_the_window_does_not_ask_only_one_kind_of_session_for_its_tail():
    """The bug was in the caller, not in either session: the worker closed the
    stream and then asked for the tail only `if isinstance(session,
    LiveSession)`. Both kinds have one."""
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parent.parent
    for path in (root / "lt_ui" / "engine.py", root / "tools" / "live.py"):
        source = path.read_text(encoding="utf-8")
        assert "finish()" in source, path.name
        for guard in ("isinstance(session, LiveSession)",
                      "isinstance(session, ConversationSession)"):
            assert guard not in source, f"{path.name}: {guard}"
    assert callable(getattr(ConversationSession, "finish", None))
    assert callable(getattr(LiveSession, "finish", None))


class FakeConversationTranscriber(FakeTranscriber):
    """A transcriber that also answers "which of these two languages"."""

    def __init__(self, script, language="en", heard=None):
        super().__init__(script, language)
        self.heard = heard or language

    def detect_between(self, audio, languages):
        return self.heard, 0.99, 0.9


def test_the_last_thing_said_is_not_lost_when_the_conversation_is_stopped():
    """The window feeds chunks itself so that it can stop on a button, and it
    used to ask only a single-speaker session for its tail. A conversation's
    last words were transcribed, held for the sentence that never came, and
    dropped."""
    script = [
        words((" Good", 0.0, 0.5), (" morning", 0.5, 1.0)),
        words((" Good", 0.0, 0.5), (" morning", 0.5, 1.0), (" there", 1.0, 1.5)),
    ]
    session = ConversationSession(
        FakeConversationTranscriber(script), _EchoTranslator(),
        Side("en", "A"), Side("ru", "B"), pace=Pace(window=1.0),
    )
    for chunk in chunks(3.0):
        session.feed(chunk)
    closing = session.finish()
    assert isinstance(closing, list)
    spoken = " ".join(
        part for update in closing
        for part in (update.committed, update.translation) if part
    )
    assert "morning" in spoken, spoken


def test_a_turn_is_routed_by_the_alphabet_it_came_out_in():
    """Committed text trails the audio by seconds, so at a handover the window
    has already changed hands while the words still belong to whoever was
    talking. Measured on a two-language dialogue: "four major features." was
    handed to the Russian side and "За последние три месяца." to the English
    one, and the translator returned both unchanged -- asking it to put English
    into English is asking for nothing."""
    session = ConversationSession.__new__(ConversationSession)
    session.left, session.right = Side("en", "A"), Side("ru", "B")
    session._left_script, session._right_script = "latin", "cyrillic"

    assert session._by_script("four major features.") == "en"
    assert session._by_script("За последние три месяца.") == "ru"


def _with_pitch(left_hz, right_hz):
    session = ConversationSession.__new__(ConversationSession)
    session.left, session.right = Side("en", "A"), Side("ru", "B")
    session._pitch = {"en": list(left_hz), "ru": list(right_hz)}
    session._registers = {}
    return session


def test_each_side_of_a_conversation_is_read_in_its_own_register():
    session = _with_pitch([95.0, 97.0, 92.0], [198.0, 201.0, 194.0])
    assert session.register_of("en") == MALE
    assert session.register_of("ru") == FEMALE


def test_two_sides_that_measure_alike_are_still_told_apart():
    """A conversation is followed by hearing who is talking, and two voices a
    few Hz apart are one voice. Measured on a real dialogue, the two languages'
    default voices came out at 179 and 182 Hz -- indistinguishable."""
    session = _with_pitch([180.0, 182.0], [188.0, 191.0])
    first = session.register_of("en")
    second = session.register_of("ru")
    assert first != second
    assert first == MALE, "the lower of the two takes the low voice"


def test_a_register_once_chosen_is_never_revisited():
    """A voice that changes halfway through is worse than one that is wrong
    about somebody's register from the start."""
    session = _with_pitch([95.0], [198.0])
    assert session.register_of("en") == MALE
    session._pitch["en"] = [210.0] * 20
    assert session.register_of("en") == MALE


def _two_sided():
    session = ConversationSession.__new__(ConversationSession)
    session.left, session.right = Side("en", "A"), Side("ru", "B")
    session._left_script, session._right_script = "latin", "cyrillic"
    return session


def test_a_commit_that_spans_a_handover_is_split_between_the_two_sides():
    """Agreement knows nothing about whose voice it is listening to, so one
    commit can hold the end of one turn and the start of the next. Measured:
    "За последние три месяца, reduced average response." came out as a single
    line, and whichever way it was sent, half of it was being translated into
    the language it was already in."""
    pieces = _two_sided()._split_by_side(
        "За последние три месяца, reduced average response.", "en"
    )
    assert pieces == [
        ("ru", "За последние три месяца,"),
        ("en", "reduced average response."),
    ]


def test_an_ordinary_turn_is_not_split_at_all():
    pieces = _two_sided()._split_by_side("Reduced latency by 31%.", "en")
    assert pieces == [("en", "Reduced latency by 31%.")]


def test_a_turn_that_opens_on_a_figure_still_belongs_to_whoever_said_it():
    pieces = _two_sided()._split_by_side("31% быстрее прежнего.", "en")
    assert pieces == [("ru", "31% быстрее прежнего.")]


def test_two_sides_sharing_an_alphabet_are_never_split():
    session = ConversationSession.__new__(ConversationSession)
    session.left, session.right = Side("en", "A"), Side("de", "B")
    session._left_script, session._right_script = "latin", "latin"
    assert session._split_by_side("Guten Morgen, good morning.", "de") == [
        ("de", "Guten Morgen, good morning.")
    ]


def test_figures_and_borrowed_words_do_not_change_whose_turn_it_is():
    session = ConversationSession.__new__(ConversationSession)
    session.left, session.right = Side("en", "A"), Side("ru", "B")
    session._left_script, session._right_script = "latin", "cyrillic"

    assert session._by_script("Снижение задержки на 31% через API") == "ru"
    assert session._by_script("Reduced latency by 31%") == "en"


def test_two_sides_sharing_an_alphabet_are_left_to_the_audio():
    """English and German look alike on the page. There the window is all
    there is, and guessing from the letters would be worse than not."""
    session = ConversationSession.__new__(ConversationSession)
    session.left, session.right = Side("en", "A"), Side("de", "B")
    session._left_script, session._right_script = "latin", "latin"

    assert session._by_script("Guten Morgen") is None


def test_a_sentence_finishing_mid_turn_is_translated_at_once():
    """It used to ask whether everything held ended on a full stop, so a turn
    that finished one and started another waited for the speaker to stop."""
    session = _holding_session()
    _released, settled, provisional = session._hold(
        "We cut spending. Then we", "en", "ru"
    )
    assert settled == "[ru] We cut spending."
    assert provisional == "[ru] Then we"


def test_somebody_who_never_finishes_a_sentence_is_still_translated():
    """A turn normally ends at a handover, which releases it. This is for
    somebody who holds the floor and never stops."""
    session = _holding_session()
    settled = ""
    for _ in range(20):
        _released, settled, _provisional = session._hold(
            "and then we did another thing, ", "en", "ru"
        )
        if settled:
            break
    assert settled.rstrip().endswith(","), settled


def _holding_session():
    """Just enough of a conversation to exercise how text is held."""
    session = ConversationSession.__new__(ConversationSession)
    session._holding = []
    session._holding_for = None
    session._preview = ("", "")
    session.translator = _EchoTranslator()
    return session


def test_held_text_waits_for_a_finished_sentence():
    """A fragment is what makes the model invent: "shipped" came back as
    "отгруженные"."""
    session = _holding_session()

    released, settled, provisional = session._hold("We cut", "en", "ru")
    assert released == "" and settled == ""
    assert provisional == "[ru] We cut", "nothing was offered meanwhile"
    released, settled, provisional = session._hold("spending sharply.", "en", "ru")
    assert settled == "[ru] We cut spending sharply."
    assert provisional == "", "the draft outlived the real thing"


def test_a_turn_change_releases_the_unfinished_sentence():
    """It will never be finished, and holding it would translate it into the
    next speaker's direction."""
    session = _holding_session()

    session._hold("An unfinished thought", "en", "ru")
    released, _settled, _provisional = session._hold("Ответ.", "ru", "en")
    assert released == "[ru] An unfinished thought"




# -- joining committed text across ticks ----------------------------------

def test_committed_text_from_two_ticks_is_spaced_as_spoken():
    """Measured in the browser screen: "with you today" and "for your
    commencement" arrived on two ticks, both stripped, and read «todayfor»."""
    from lt_core.asr.types import Word
    from lt_core.realtime.session import LiveUpdate, _starts_word, append_committed

    words = [Word(" for", 1.0, 1.2, 0.9), Word(" your", 1.2, 1.4, 0.9)]
    update = LiveUpdate(committed="for your", committed_space=_starts_word(words))
    assert append_committed("with you today", update) == "with you today for your"


def test_a_word_continued_on_the_next_tick_stays_joined():
    """Whisper can split "$12,000" into " $12" and ",000". A space between
    them is a different number to anyone reading it."""
    from lt_core.asr.types import Word
    from lt_core.realtime.session import LiveUpdate, _starts_word, append_committed

    words = [Word(",000", 2.0, 2.3, 0.9)]
    update = LiveUpdate(committed=",000", committed_space=_starts_word(words))
    assert append_committed("It cost $12", update) == "It cost $12,000"


def test_the_first_committed_text_needs_no_joiner():
    from lt_core.realtime.session import LiveUpdate, append_committed

    assert append_committed("", LiveUpdate(committed="Hello")) == "Hello"
    assert append_committed("Hello", LiveUpdate(committed="")) == "Hello"


class _UnsureTranscriber(FakeTranscriber):
    """Unsure on its first ticks -- a video's opening music -- then sure."""

    def __init__(self, script, answers):
        super().__init__(script)
        self.answers = answers

    def transcribe(self, audio, options=None, on_progress=None, total_duration=None):
        from dataclasses import replace

        result = super().transcribe(audio, options, on_progress, total_duration)
        language, probability = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        return replace(result, language=language, language_probability=probability)


def test_the_language_is_not_pinned_off_an_unsure_window():
    """A German talk run as English came out as English words and loops.
    Detecting fixes that -- unless the opening music is detected, at low
    confidence, as English and pinned for the rest of the video."""
    transcriber = _UnsureTranscriber(
        [words((" Hallo", 0, 0.5))],
        answers=[("en", 0.31), ("en", 0.42), ("de", 0.99)],
    )
    session = LiveSession(transcriber, pace=Pace(window=1.0))
    for chunk in chunks(4.5):
        session.feed(chunk)
    assert session.source_language == "de"


def test_a_window_with_no_words_does_not_pin_a_language():
    transcriber = _UnsureTranscriber([[]], answers=[("en", 0.95)])
    session = LiveSession(transcriber, pace=Pace(window=1.0))
    for chunk in chunks(2.5):
        session.feed(chunk)
    assert session.source_language is None


def test_a_translation_says_which_words_it_translated():
    """So a screen can put the sentence and its translation on one line,
    rather than whatever had been committed by the time it arrived."""
    script = [
        words((" Hello.", 0.0, 0.5), (" How", 0.5, 1.0)),
        words((" Hello.", 0.0, 0.5), (" How", 0.5, 1.0), (" are", 1.0, 1.5)),
    ]
    session = LiveSession(
        FakeTranscriber(script), translator=_EchoTranslator(),
        source_language="en", target_language="ru", pace=Pace(window=1.0),
    )
    translated = [
        update
        for update in (session.feed(chunk) for chunk in chunks(3.0))
        if update and update.translation
    ]
    assert translated
    assert translated[0].translation_source == "Hello."
    # Updates with no translation carry no source.
    assert session.finish().translation_source in ("", "How are")


def test_live_translation_does_not_stop_at_an_abbreviation():
    script = [
        words((" Tools", 0.0, 0.4), (" wie", 0.4, 0.6), (" z.B.", 0.6, 1.0), (" Gmail", 1.0, 1.4)),
        words((" Tools", 0.0, 0.4), (" wie", 0.4, 0.6), (" z.B.", 0.6, 1.0), (" Gmail", 1.0, 1.4),
              (" verbinden.", 1.4, 2.0)),
        words((" Tools", 0.0, 0.4), (" wie", 0.4, 0.6), (" z.B.", 0.6, 1.0), (" Gmail", 1.0, 1.4),
              (" verbinden.", 1.4, 2.0), (" Gut", 2.0, 2.4)),
    ]
    session = LiveSession(
        FakeTranscriber(script), translator=_EchoTranslator(),
        source_language="de", target_language="ru", pace=Pace(window=1.0),
    )
    sources = [
        update.translation_source
        for update in (session.feed(chunk) for chunk in chunks(4.0))
        if update and update.translation
    ]
    assert sources and sources[0] == "Tools wie z.B. Gmail verbinden."


def test_the_users_words_reach_the_live_prompt():
    """«Слова из записи» reached file mode and never the live one; on a real
    German video «ChatGBT», «Cloud» and «Google-Cheat» came right with them."""
    session = LiveSession(
        FakeTranscriber([]), source_language="de", terms=("ChatGPT", "Claude"),
    )
    prompt = session._prompt()
    assert prompt is not None and prompt.endswith("ChatGPT, Claude.")
