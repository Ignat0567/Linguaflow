"""Day 7: pitch, casting voices to speakers, and the dubbed video copy."""

from __future__ import annotations

import numpy as np
import pytest

from lt_core import languages
from lt_core.audio.pitch import estimate
from lt_core.subtitles.cues import Cue
from lt_core.tts import casting
from lt_core.tts.casting import FEMALE, MALE, choose_split


def tone(frequency: float, seconds: float, rate: int = 16_000) -> np.ndarray:
    """A voice-like periodic signal: a fundamental plus two harmonics.

    A bare sine wave is not a fair test. A real voice carries harmonics, and
    an estimator can find a plausible peak in a pure tone while failing on
    anything with overtones -- which is everything a person says.
    """
    t = np.arange(int(seconds * rate)) / rate
    wave = (
        0.6 * np.sin(2 * np.pi * frequency * t)
        + 0.3 * np.sin(2 * np.pi * 2 * frequency * t)
        + 0.15 * np.sin(2 * np.pi * 3 * frequency * t)
    )
    return (wave * 0.5).astype(np.float32)


def cues_of(count: int, length: float = 1.0) -> tuple[Cue, ...]:
    return tuple(
        Cue(index=i + 1, start=i * length, end=(i + 1) * length,
            lines=(f"строка {i}",))
        for i in range(count)
    )


# -- measuring pitch -----------------------------------------------------

@pytest.mark.parametrize("frequency", [90.0, 120.0, 155.0, 200.0, 260.0])
def test_pitch_is_measured_within_a_couple_of_hertz(frequency):
    measured = estimate(tone(frequency, 1.0), 16_000)
    assert measured.confident
    assert measured.median == pytest.approx(frequency, rel=0.02)


def test_silence_has_no_pitch():
    """Not a low pitch, and not a confident one: none."""
    measured = estimate(np.zeros(16_000, dtype=np.float32), 16_000)
    assert not measured.confident
    assert measured.median == 0.0


def test_noise_is_not_reported_as_a_voice():
    generator = np.random.default_rng(7)
    noise = (generator.normal(0, 0.2, 16_000)).astype(np.float32)
    assert not estimate(noise, 16_000).confident


def test_a_fragment_too_short_to_judge_is_not_judged():
    """120 ms is about one syllable, and the floor a median can rest on."""
    assert not estimate(tone(110.0, 0.05), 16_000).confident


def test_pitch_does_not_octave_halve_on_a_strong_second_harmonic():
    """The classic failure: report 55 Hz for a 110 Hz voice.

    Autocorrelation errs towards the longer period, so a signal whose second
    harmonic is as loud as its fundamental is where it happens.
    """
    t = np.arange(16_000) / 16_000
    wave = 0.5 * np.sin(2 * np.pi * 110 * t) + 0.5 * np.sin(2 * np.pi * 220 * t)
    measured = estimate((wave * 0.5).astype(np.float32), 16_000)
    assert measured.median == pytest.approx(110.0, rel=0.03)


# -- choosing the threshold ---------------------------------------------

def test_two_speakers_put_the_threshold_in_their_own_gap():
    """Measured on real recordings: a male cluster near 90, a female near 195.

    The threshold belongs between the groups, not at a number chosen in
    advance -- which is the whole reason it is computed.
    """
    pitches = [88, 91, 92, 95, 99, 187, 192, 193, 199, 209]
    split, from_recording = choose_split(pitches)
    assert from_recording
    assert 99 < split < 187


def test_one_speaker_does_not_get_split_in_half():
    """A single voice ranges over a recording. That is not two people."""
    split, from_recording = choose_split([88, 92, 95, 99, 101, 96, 90, 93])
    assert not from_recording
    assert split == casting.DEFAULT_SPLIT


def test_too_few_measurements_fall_back_rather_than_invent_a_split():
    split, from_recording = choose_split([95, 190])
    assert not from_recording
    assert split == casting.DEFAULT_SPLIT


def test_the_default_threshold_sits_in_the_band_measured_as_empty():
    """120-160 Hz held no measurements across four real recordings."""
    assert 120.0 < casting.DEFAULT_SPLIT < 160.0


# -- casting -------------------------------------------------------------

def test_a_two_speaker_recording_is_cast_as_two_voices():
    rate = 16_000
    cues = cues_of(6)
    audio = np.concatenate(
        [tone(95.0, 1.0, rate)] * 3 + [tone(195.0, 1.0, rate)] * 3
    )
    cast = casting.analyse(cues, audio, rate)
    assert cast.is_mixed
    assert cast.genders == [MALE] * 3 + [FEMALE] * 3
    assert cast.from_recording


def test_one_speaker_is_read_by_one_voice():
    rate = 16_000
    cues = cues_of(5)
    audio = np.concatenate([tone(98.0, 1.0, rate)] * 5)
    cast = casting.analyse(cues, audio, rate)
    assert not cast.is_mixed
    assert set(cast.genders) == {MALE}


def test_a_cue_with_nothing_voiced_goes_to_whoever_talks_most():
    """Applause or silence should not become a third speaker."""
    rate = 16_000
    cues = cues_of(4)
    audio = np.concatenate([
        tone(96.0, 1.0, rate),
        np.zeros(rate, dtype=np.float32),
        tone(94.0, 1.0, rate),
        tone(97.0, 1.0, rate),
    ])
    cast = casting.analyse(cues, audio, rate)
    assert cast.unmeasured == 1
    assert cast.genders == [MALE] * 4


def test_a_borderline_line_follows_its_neighbours():
    """One sentence does not change a speaker's sex and then change it back."""
    genders = [MALE, FEMALE, MALE]
    pitches = [
        estimate(tone(95.0, 0.5), 16_000),
        estimate(tone(casting.DEFAULT_SPLIT + 4.0, 0.5), 16_000),
        estimate(tone(95.0, 0.5), 16_000),
    ]
    assert casting._smooth(genders, pitches, casting.DEFAULT_SPLIT) == [MALE] * 3


def test_a_clear_speaker_change_is_never_smoothed_away():
    """The thing this feature exists for must not be tidied out of existence."""
    genders = [MALE, FEMALE, MALE]
    pitches = [
        estimate(tone(95.0, 0.5), 16_000),
        estimate(tone(210.0, 0.5), 16_000),
        estimate(tone(95.0, 0.5), 16_000),
    ]
    assert casting._smooth(genders, pitches, casting.DEFAULT_SPLIT) == genders


def test_the_summary_says_where_the_threshold_came_from():
    rate = 16_000
    audio = np.concatenate(
        [tone(95.0, 1.0, rate)] * 3 + [tone(195.0, 1.0, rate)] * 3
    )
    summary = casting.analyse(cues_of(6), audio, rate).summary()
    assert "3 мужских" in summary and "3 женских" in summary
    assert "по записи" in summary


# -- the voice catalogue -------------------------------------------------

def test_every_offered_language_can_dub_two_speakers():
    for code in languages.ACTIVE:
        assert languages.has_voice_pair(code), code


def test_the_paired_voices_are_actually_installed():
    """A setting that silently cannot be honoured is worse than one refused."""
    from lt_ui.store import MODEL_ROOT

    for code in languages.ACTIVE:
        for gender in (MALE, FEMALE):
            voice = languages.voice_for(code, gender)
            assert (MODEL_ROOT / "piper" / f"{voice}.onnx").exists(), voice


def test_a_language_without_a_pair_falls_back_to_its_own_voice():
    """Never to the other gender's: that is the mistake being avoided."""
    assert not languages.has_voice_pair("ja")
    japanese = languages.CATALOGUE["ja"]
    assert languages.voice_for("ja", MALE) == japanese.piper_voice
    assert languages.voice_for("ja", FEMALE) == japanese.piper_voice


def test_russian_pair_is_the_measured_one_not_the_default_voice():
    """`dmitri` measures at 186 Hz -- inside the female range.

    Pairing it with `irina` at 177 Hz would have produced two voices a
    listener cannot tell apart, which is the bug this records.
    """
    assert languages.voice_for("ru", MALE) == "ru_RU-ruslan-medium"
    assert languages.voice_for("ru", FEMALE) == "ru_RU-irina-medium"
    assert languages.CATALOGUE["ru"].piper_voice == "ru_RU-dmitri-medium"


def test_track_language_uses_the_code_a_container_understands():
    assert languages.track_language("ru") == "rus"
    assert languages.track_language("de") == "deu"
    assert languages.track_language("qq") == "und"
