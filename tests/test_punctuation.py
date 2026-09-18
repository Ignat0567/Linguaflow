"""Day 7: making the recogniser punctuate what it hears.

Left alone, this model punctuated the first minute of a recording and then
stopped, and a transcript with no sentence ends is not merely hard to read:
the translator splits on sentence ends, so the translation went with it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lt_core import languages
from lt_core.asr.transcriber import TranscribeOptions, Transcriber


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
    assert model.calls[0]["initial_prompt"] == languages.punctuation_sample("en")


def test_the_sample_matches_the_language_being_transcribed():
    """A prompt in the wrong language is the one way this is known to harm."""
    transcriber, model = build()
    transcriber.transcribe("clip.wav", TranscribeOptions(language="de"))
    assert model.calls[0]["initial_prompt"] == languages.punctuation_sample("de")


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
    assert model.calls[0]["initial_prompt"] == "Acme Corp, Q3, EBITDA."


def test_the_sample_can_be_turned_off():
    transcriber, model = build()
    transcriber.transcribe(
        "clip.wav", TranscribeOptions(language="en", punctuation_prompt=False)
    )
    assert model.calls[0]["initial_prompt"] is None


def test_context_is_carried_between_windows_in_file_mode():
    """What takes the problem recording from 23 sentence ends to 184."""
    transcriber, model = build()
    transcriber.transcribe("clip.wav", TranscribeOptions(language="en"))
    assert model.calls[0]["condition_on_previous_text"] is True


def test_the_silence_guard_is_off():
    """Aimed at hallucination loops, it cut 111 characters of real speech."""
    transcriber, model = build()
    transcriber.transcribe("clip.wav", TranscribeOptions(language="en"))
    assert model.calls[0]["hallucination_silence_threshold"] is None


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
    assert model.calls[0]["hallucination_silence_threshold"] is None


def test_detection_does_not_run_when_the_language_is_known():
    """It costs a probe of the opening seconds; on a live window that would be
    one probe per tick, which is why the live path opts out entirely."""
    transcriber, model = build()
    transcriber.transcribe("clip.wav", TranscribeOptions(language="en"))
    assert len(model.calls) == 1
    assert model.calls[0]["language"] == "en"


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


@pytest.mark.parametrize("code", ["ru", "en", "de"])
def test_a_sample_is_short_enough_to_be_context_not_content(code):
    """Whisper's prompt window is limited, and a long sample would crowd out
    the audio's own context."""
    assert len(languages.punctuation_sample(code)) < 200
