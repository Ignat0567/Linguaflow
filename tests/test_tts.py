"""Day 5: speaking the translation, and fitting it to the original's timing."""

from __future__ import annotations

import numpy as np
import pytest

from lt_core import languages
from lt_core.subtitles.cues import Cue
from lt_core.tts import dub as dubbing
from lt_core.tts.speaker import (
    MAX_LENGTH_SCALE,
    MIN_LENGTH_SCALE,
    Speaker,
    Utterance,
    VoiceError,
    resample,
)


def cue(index, start, end, text):
    return Cue(index=index, start=start, end=end, lines=(text,))


class FakeSpeaker:
    """Speaks at a fixed number of seconds per character."""

    def __init__(self, seconds_per_char=0.08, rate=22_050):
        self.seconds_per_char = seconds_per_char
        self.rate = rate

    def fit(self, text, start, seconds):
        natural = len(text) * self.seconds_per_char
        scale = 1.0
        if natural > seconds * 1.02:
            scale = max(MIN_LENGTH_SCALE, seconds / natural)
        length = int(natural * scale * self.rate)
        tone = np.sin(np.linspace(0, 200, max(length, 1))).astype(np.float32) * 0.5
        return Utterance(tone, self.rate, start, seconds, scale)


# -- voice selection -----------------------------------------------------

def test_every_offered_language_has_a_voice():
    for code in languages.ACTIVE:
        assert languages.CATALOGUE[code].piper_voice


def test_a_missing_voice_says_how_to_get_it(tmp_path):
    """An error that names the command is worth more than one that names a path."""
    with pytest.raises(VoiceError) as caught:
        Speaker("ru", voices_dir=tmp_path)
    assert "download_voices" in str(caught.value)
    assert "ru_RU-dmitri-medium" in str(caught.value)


def test_a_language_without_a_voice_is_refused(tmp_path, monkeypatch):
    monkeypatch.setitem(
        languages.CATALOGUE, "xx",
        languages.Language("xx", "тест", "Test", "xxx_Latn", "xxx", "XX", "XX"),
    )
    with pytest.raises(VoiceError, match="не задан голос"):
        Speaker("xx", voices_dir=tmp_path)


# -- fitting -------------------------------------------------------------

def test_a_line_that_already_fits_is_not_touched():
    """Never stretched to fill a slot: a drawling dub is worse than a short one."""
    speaker = FakeSpeaker()
    utterance = speaker.fit("short", 0.0, 10.0)
    assert utterance.length_scale == 1.0


def test_a_long_line_is_compressed():
    speaker = FakeSpeaker()
    utterance = speaker.fit("a considerably longer sentence than fits", 0.0, 1.0)
    assert utterance.length_scale < 1.0


def test_compression_stops_at_the_human_limit():
    """Past this the voice stops sounding like a person, and a viewer notices
    that long before they notice a line ending late."""
    speaker = FakeSpeaker()
    utterance = speaker.fit("x" * 400, 0.0, 0.5)
    assert utterance.length_scale >= MIN_LENGTH_SCALE


def test_the_scale_never_slows_speech_down():
    assert MAX_LENGTH_SCALE == 1.0


def test_an_overrun_is_reported_not_hidden():
    speaker = FakeSpeaker()
    utterance = speaker.fit("x" * 200, 0.0, 0.5)
    assert utterance.overran


# -- track assembly ------------------------------------------------------

def test_each_line_lands_at_its_own_timestamp():
    cues = (cue(1, 0.0, 2.0, "first line"), cue(2, 5.0, 7.0, "second line"))
    result = dubbing.synthesise_track(cues, FakeSpeaker(), 8.0, rate=16_000)

    quiet = result.samples[int(3.0 * 16_000):int(4.5 * 16_000)]
    assert np.abs(quiet).max() < 0.01, "the gap between lines must stay empty"
    for start in (0.0, 5.0):
        at = result.samples[int(start * 16_000):int((start + 0.5) * 16_000)]
        assert np.abs(at).max() > 0.05


def test_an_overrunning_line_overlaps_rather_than_being_cut():
    """A person talking over the end of a sentence is what this sounds like;
    a line chopped mid-word is not."""
    cues = (cue(1, 0.0, 0.5, "a sentence far too long for half a second"),)
    result = dubbing.synthesise_track(cues, FakeSpeaker(), 10.0, rate=16_000)
    tail = result.samples[int(1.0 * 16_000):int(1.5 * 16_000)]
    assert np.abs(tail).max() > 0.05


def test_the_track_never_clips():
    """Overlapping lines sum, and clipping is audible."""
    cues = tuple(cue(n, n * 0.1, n * 0.1 + 3.0, "overlapping line") for n in range(8))
    result = dubbing.synthesise_track(cues, FakeSpeaker(), 6.0, rate=16_000)
    assert np.abs(result.samples).max() <= 0.99


def test_empty_cues_are_skipped():
    cues = (cue(1, 0.0, 2.0, "   "), cue(2, 3.0, 5.0, "real"))
    result = dubbing.synthesise_track(cues, FakeSpeaker(), 6.0, rate=16_000)
    assert result.spoken == 1


# -- ducking -------------------------------------------------------------

def test_the_original_is_turned_down_under_the_dub():
    rate = 16_000
    original = np.ones(10 * rate, dtype=np.float32) * 0.5
    cues = (cue(1, 2.0, 4.0, "spoken here"),)
    ducked = dubbing.duck(original, cues, rate)

    under = np.abs(ducked[int(2.5 * rate):int(3.5 * rate)]).mean()
    clear = np.abs(ducked[int(7.0 * rate):int(8.0 * rate)]).mean()
    assert under < clear / 4


def test_the_original_is_not_silenced():
    """It is kept so a listener can hear who is speaking, and check a
    translation the numeric audit has flagged."""
    rate = 16_000
    original = np.ones(6 * rate, dtype=np.float32) * 0.5
    ducked = dubbing.duck(original, (cue(1, 0.0, 6.0, "x"),), rate)
    assert np.abs(ducked).mean() > 0.0


def test_ducking_fades_rather_than_steps():
    rate = 16_000
    original = np.ones(10 * rate, dtype=np.float32) * 0.5
    ducked = dubbing.duck(original, (cue(1, 5.0, 7.0, "x"),), rate)
    edge = np.abs(np.diff(ducked[int(4.8 * rate):int(5.2 * rate)]))
    assert edge.max() < 0.05, "a level jump is audible as a click"


# -- resampling ----------------------------------------------------------

def test_resampling_preserves_duration():
    samples = np.sin(np.linspace(0, 100, 22_050)).astype(np.float32)
    out = resample(samples, 22_050, 16_000)
    assert out.size == pytest.approx(16_000, rel=0.02)


def test_resampling_is_a_no_op_at_the_same_rate():
    samples = np.zeros(10, dtype=np.float32)
    assert resample(samples, 16_000, 16_000) is samples
