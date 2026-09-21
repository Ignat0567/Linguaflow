"""Day 7: making the recogniser punctuate what it hears.

Left alone, this model punctuated the first minute of a recording and then
stopped, and a transcript with no sentence ends is not merely hard to read:
the translator splits on sentence ends, so the translation went with it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lt_core import languages
from lt_core.asr.transcriber import (
    TranscribeOptions,
    Transcriber,
    is_hallucinated,
    is_prompt_echo,
)


class FakeModel:
    """Records what it was asked for, and answers with one plain segment."""

    def __init__(self, detected: str = "en") -> None:
        self.calls: list[dict] = []
        self.detected = detected

    def transcribe(self, source, **kwargs):
        self.calls.append(kwargs)
        segment = SimpleNamespace(
            text="Hello there.", start=0.0, end=1.0, words=[],
            avg_logprob=-0.2, no_speech_prob=0.0,
        )
        info = SimpleNamespace(
            language=kwargs.get("language") or self.detected,
            language_probability=1.0, duration=1.0,
        )
        return iter([segment]), info

    def detect_language(self, audio=None):
        return self.detected, 1.0, [(self.detected, 1.0), ("de", 0.0)]


def build(detected: str = "en") -> tuple[Transcriber, FakeModel]:
    transcriber = Transcriber.__new__(Transcriber)
    model = FakeModel(detected)
    transcriber._model = model
    transcriber.model_name = "fake"
    return transcriber, model


# -- the catalogue -------------------------------------------------------

def test_every_offered_language_has_a_sample():
    for code in languages.ACTIVE:
        assert languages.punctuation_sample(code), code


def test_every_sample_is_itself_punctuated():
    """Priming the model with unpunctuated text would teach it the opposite."""
    for code, language in languages.CATALOGUE.items():
        sample = language.punctuation_sample
        assert sample, code
        assert any(end in sample for end in ".。"), code
        assert any(mark in sample for mark in ",，、"), code


def test_a_sample_exists_even_for_languages_not_offered():
    """They are switched off, not unfinished."""
    assert languages.punctuation_sample("ja")
    assert languages.punctuation_sample("fr")


def test_an_unknown_language_has_no_sample_rather_than_a_wrong_one():
    assert languages.punctuation_sample("qq") == ""


# -- what reaches the model ---------------------------------------------

def test_the_sample_is_sent_as_the_opening_context():
    transcriber, model = build()
    transcriber.transcribe("clip.wav", TranscribeOptions(language="en"))
    assert model.calls[-1]["initial_prompt"] == languages.punctuation_sample("en")


def test_the_sample_matches_the_language_being_transcribed():
    """A prompt in the wrong language is the one way this is known to harm."""
    transcriber, model = build()
    transcriber.transcribe("clip.wav", TranscribeOptions(language="de"))
    assert model.calls[-1]["initial_prompt"] == languages.punctuation_sample("de")


def test_the_language_is_settled_before_the_sample_is_chosen():
    """With no language given, detection runs first so the sample can match.

    Detection goes through the model's own transcribe call, so there are two:
    the probe, and then the real pass carrying the matching sample.
    """
    transcriber, model = build(detected="de")
    transcriber.transcribe("clip.wav", TranscribeOptions(language=None))
    assert len(model.calls) == 2
    assert model.calls[-1]["initial_prompt"] == languages.punctuation_sample("de")
    assert model.calls[-1]["language"] == "de"


def test_an_explicit_prompt_wins():
    """Saying something specific about one recording must still be possible."""
    transcriber, model = build()
    transcriber.transcribe(
        "clip.wav",
        TranscribeOptions(language="en", initial_prompt="Acme Corp, Q3, EBITDA."),
    )
    assert model.calls[-1]["initial_prompt"] == "Acme Corp, Q3, EBITDA."


def test_the_sample_can_be_turned_off():
    transcriber, model = build()
    transcriber.transcribe(
        "clip.wav", TranscribeOptions(language="en", punctuation_prompt=False)
    )
    assert model.calls[-1]["initial_prompt"] is None


def test_context_is_carried_between_windows_in_file_mode():
    """What takes the problem recording from 23 sentence ends to 184."""
    transcriber, model = build()
    transcriber.transcribe("clip.wav", TranscribeOptions(language="en"))
    assert model.calls[-1]["condition_on_previous_text"] is True


def test_the_silence_guard_is_off():
    """Aimed at hallucination loops, it cut 111 characters of real speech."""
    transcriber, model = build()
    transcriber.transcribe("clip.wav", TranscribeOptions(language="en"))
    assert model.calls[-1]["hallucination_silence_threshold"] is None


def test_the_silence_guard_needs_word_timestamps():
    """It works off word timings; without them it would be asked for nothing."""
    transcriber, model = build()
    transcriber.transcribe(
        "clip.wav",
        TranscribeOptions(
            language="en", word_timestamps=False,
            hallucination_silence_threshold=2.0,
        ),
    )
    assert model.calls[-1]["hallucination_silence_threshold"] is None


def test_a_named_language_is_checked_against_the_recording():
    """Whisper never refuses a language it is given: told that Russian speech
    is English, it writes fluent English and reports a probability of 1.0,
    because it was not asked. Measured on a twelve-minute file whose container
    defaults to a dubbed Russian track -- 2718 words of real English in the
    original against 1145 words of invented English from the dub.

    One probe of the opening, not one per window: the live path opts out.
    """
    transcriber, model = build(detected="ru")
    transcript = transcriber.transcribe(
        "clip.wav", TranscribeOptions(language="en"))
    assert len(model.calls) == 2, "the probe, then the pass that was asked for"
    assert model.calls[-1]["language"] == "en", "the named language is still used"
    assert transcript.detected_language == "ru"
    assert transcript.language_looks_wrong


def test_a_named_language_the_recording_agrees_with_raises_nothing():
    transcriber, model = build(detected="en")
    transcript = transcriber.transcribe(
        "clip.wav", TranscribeOptions(language="en"))
    assert not transcript.language_looks_wrong


def test_the_check_can_be_turned_off():
    """A caller that already knows -- the live path -- pays nothing for it."""
    transcriber, model = build(detected="ru")
    transcript = transcriber.transcribe(
        "clip.wav",
        TranscribeOptions(language="en", punctuation_prompt=False,
                          verify_language=False),
    )
    assert len(model.calls) == 1
    assert not transcript.language_looks_wrong


def test_an_unsure_detector_is_not_allowed_to_contradict_the_caller():
    """Detection is fallible too, and a warning shown over a correct choice
    teaches people to ignore warnings."""
    from lt_core.asr.types import Transcript

    unsure = Transcript(
        segments=(), language="en", language_probability=1.0, duration=1.0,
        detected_language="ru", detected_probability=0.5,
    )
    assert not unsure.language_looks_wrong


# -- the live path keeps its own arrangement ----------------------------

def test_the_live_session_opts_out_of_both():
    """A live window is two seconds, and its context is supplied deliberately
    as committed words. Detecting a language per window would be worse still.
    """
    import inspect

    from lt_core.realtime import session

    source = inspect.getsource(session.LiveSession._tick)
    assert "punctuation_prompt=False" in source
    assert "condition_on_previous_text=False" in source
    assert "verify_language=False" in source


@pytest.mark.parametrize("code", ["ru", "en", "de"])
def test_a_sample_is_short_enough_to_be_context_not_content(code):
    """Whisper's prompt window is limited, and a long sample would crowd out
    the audio's own context."""
    assert len(languages.punctuation_sample(code)) < 200


# -- the credits this model invents over silence -------------------------

@pytest.mark.parametrize("text", [
    "Субтитры сделал DimaTorzok",
    "Субтитры создавал DimaTorzok",
    "Субтитры сделал DimaTorzok.",
    "Субтитры: DimaTorzok",
    "DimaTorzok",
    "Редактор субтитров А.Синецкая Корректор А.Кулакова",
    "Продолжение следует...",
    "Спасибо за просмотр!",
    "Подписывайтесь на канал",
    "Subtitles by the Amara.org community",
    "Subtitles by Stephanie Geiges",
    "Thanks for watching!",
    "Please subscribe!",
    "Untertitel von Stephanie Geiges",
    "Vielen Dank fürs Zuschauen",
])
def test_a_subtitle_credit_is_not_something_anybody_said(text):
    """Whisper was trained on subtitle files, credits and all, so given silence
    or room noise it returns the likeliest line in a subtitle file with no
    dialogue in it. Live, with the VAD filter deliberately off, that reaches
    the screen: a user testing the microphone watched "Субтитры сделал
    DimaTorzok" arrive as a turn, get attributed to a speaker, and be
    translated into "Subtitles made".
    """
    assert is_hallucinated(text), text


@pytest.mark.parametrize("text", [
    "Мы обсудим субтитры на следующей встрече",
    "Редактор субтитров подготовил отчёт вчера вечером",
    "Субтитры сделал наш редактор за вечер",
    "Перевод занял три недели",
    "Subtitles are useful for learning",
    "Subtitles by themselves are not enough here",
    "Please subscribe your team to the newsletter by Friday",
    "Thanks for watching the demo and telling me what broke",
    "Спасибо за внимание, вопросы?",
    "Продолжение следует за этим разделом",
])
def test_speech_that_merely_mentions_subtitles_is_still_speech(text):
    """Deleting what somebody actually said is the worse failure of the two, so
    a credit has to name somebody: a capitalised name is what separates
    "Редактор субтитров А.Синецкая" from "Редактор субтитров подготовил
    отчёт"."""
    assert not is_hallucinated(text), text


def test_the_german_closer_is_a_prompt_echo():
    """The 19-minute lecture: «Fangen wir an?» twenty-eight times, then speech."""
    prompt = languages.punctuation_sample("de")
    assert is_prompt_echo("Fangen wir an?", prompt)
    assert is_prompt_echo("Fangen wir an? Fangen wir an?", prompt)
    assert is_prompt_echo("Fangen wir", prompt)


def test_real_german_speech_is_not_the_prompt():
    assert not is_prompt_echo(
        "Das ist eine schlechte Bewegung.",
        languages.punctuation_sample("de"),
    )


def test_the_english_closer_is_a_prompt_echo():
    prompt = languages.punctuation_sample("en")
    assert is_prompt_echo("Shall we begin?", prompt)
    assert not is_prompt_echo(
        "So what I just figured out might break the game.", prompt
    )


def test_the_whole_segment_has_to_be_the_credit():
    """Matching a fragment would take a sentence with a stray "продолжение
    следует" inside it down with the credit."""
    assert not is_hallucinated(
        "Продолжение следует, и мы вернёмся к этому в третьем разделе"
    )


def test_a_dropped_segment_takes_its_words_with_it():
    """`Transcript.words` is built from the segments, and the live path reads
    words rather than text -- a segment filtered out of one and left in the
    other would put the credit back on screen."""
    from lt_core.asr.types import Segment, Transcript, Word

    kept = Segment(
        text="Good morning.", start=0.0, end=1.0,
        words=(Word(text=" Good", start=0.0, end=0.5),
               Word(text=" morning.", start=0.5, end=1.0)),
    )
    transcript = Transcript(segments=(kept,), language="en",
                            language_probability=1.0, duration=1.0)
    assert [word.text for word in transcript.words] == [" Good", " morning."]


# -- words the recording uses that the model will not guess --------------

def test_a_term_is_named_after_the_punctuated_sample_not_instead_of_it():
    """The sample is what makes the model punctuate, and a transcript with no
    sentence ends loses most of its translation further down the line. Trading
    that away to fix one spelling would be a poor bargain."""
    from lt_core.asr.transcriber import _with_terms

    prompt = _with_terms("Hello, and welcome. Shall we begin?", ("coordination",))
    assert prompt.startswith("Hello, and welcome. Shall we begin?")
    assert prompt.endswith("coordination.")


def test_terms_are_listed_once_each_and_emptiness_is_ignored():
    from lt_core.asr.transcriber import _with_terms

    assert _with_terms("Hi.", ("  ", "Piper", "Piper", "NLLB")) == "Hi. Piper, NLLB."
    assert _with_terms("Hi.", ()) == "Hi."
    assert _with_terms("Hi.", ("  ",)) == "Hi."


def test_terms_alone_are_still_a_prompt():
    """A language with no punctuated sample of its own still gets the words."""
    from lt_core.asr.transcriber import _with_terms

    assert _with_terms(None, ("Kubernetes",)) == "Kubernetes."
    assert _with_terms(None, ()) is None


def test_the_recogniser_is_actually_given_them(monkeypatch):
    """Through the option, not by the caller assembling a prompt itself --
    otherwise the punctuation sample and the terms would each overwrite the
    other depending on who called."""
    from lt_core.asr.transcriber import TranscribeOptions, Transcriber

    seen = {}

    class Model:
        def transcribe(self, source, **kwargs):
            seen.update(kwargs)
            return iter(()), SimpleNamespace(
                language="en", language_probability=1.0, duration=1.0
            )

    transcriber = Transcriber.__new__(Transcriber)
    transcriber._model = Model()
    transcriber.model_name = "test"
    transcriber.transcribe(
        "clip.wav",
        TranscribeOptions(language="en", terms=("coordination", "Anthropic")),
    )
    assert "coordination, Anthropic." in seen["initial_prompt"]


@pytest.mark.parametrize("typed,expected", [
    ("coordination", ("coordination",)),
    ("Kubernetes, Anthropic; Piper", ("Kubernetes", "Anthropic", "Piper")),
    ("Lingua Flow, DimaTorzok", ("Lingua Flow", "DimaTorzok")),
    ("  spaced  ,  out  ", ("spaced", "out")),
    ("same, same", ("same",)),
    ("", ()),
])
def test_however_somebody_chose_to_separate_them(typed, expected):
    """A list that only works one way is a list that silently does nothing
    half the time."""
    from lt_ui.store import split_terms

    assert split_terms(typed) == expected
