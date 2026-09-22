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


def spoken(start, seconds, rate=16_000):
    """An utterance of a given length, for testing what it is ducked over."""
    samples = np.zeros(int(seconds * rate), dtype=np.float32)
    return Utterance(samples, rate, start, seconds, 1.0)


class FakeSpeaker:
    """Speaks at a fixed number of seconds per character."""

    def __init__(self, seconds_per_char=0.08, rate=22_050):
        self.seconds_per_char = seconds_per_char
        self.rate = rate

    def fit(self, text, start, seconds, fastest=None):
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
    """Within EARLY_START of it, and never after it.

    A line that does not fit may begin in the silence before it was said
    rather than talk over the line after it -- half a second ahead of the
    picture is a dub, two voices at once is a mess. The allowance is bounded,
    so the gap between two well-spaced lines is still silent.
    """
    cues = (cue(1, 0.0, 2.0, "first line"), cue(2, 5.0, 7.0, "second line"))
    result = dubbing.synthesise_track(cues, FakeSpeaker(), 8.0, rate=16_000)

    quiet = result.samples[int(3.0 * 16_000):int(3.9 * 16_000)]
    assert np.abs(quiet).max() < 0.01, "the gap between lines must stay empty"
    for start in (0.0, 5.0):
        at = result.samples[int(start * 16_000):int((start + 0.5) * 16_000)]
        assert np.abs(at).max() > 0.05


def test_a_line_never_starts_later_than_it_was_said():
    """Early is a concession to length; late would be a drift."""
    cues = (cue(1, 0.0, 2.0, "first"), cue(2, 5.0, 7.0, "second"))
    result = dubbing.synthesise_track(cues, FakeSpeaker(), 8.0, rate=16_000)
    for spoken, source in zip(result.utterances, cues):
        assert spoken.start <= source.start + 1e-6


def test_a_line_never_starts_more_than_the_allowance_early():
    cues = (cue(1, 0.0, 2.0, "first"), cue(2, 20.0, 22.0, "second"))
    result = dubbing.synthesise_track(cues, FakeSpeaker(), 24.0, rate=16_000)
    for spoken, source in zip(result.utterances, cues):
        assert spoken.start >= source.start - dubbing.EARLY_START - 1e-6


def test_a_line_never_starts_before_the_one_before_it_has_finished():
    """The allowance buys silence, not a second voice."""
    cues = (cue(1, 0.0, 6.0, "a long first line"), cue(2, 6.2, 8.0, "second"))
    result = dubbing.synthesise_track(cues, FakeSpeaker(), 10.0, rate=16_000)
    first, second = result.utterances[0], result.utterances[1]
    assert second.start >= first.start + first.duration - 1e-6


def test_silence_before_a_line_is_spent_before_the_line_is_rushed():
    """"Перевод иногда получается быстрее, чем голос говорящего" -- and it was,
    because the allowance was only reached once a line had already been
    squeezed as far as it would go. A listener notices a line that starts early
    far less than one that is gabbled, and the silence in front of it is time
    nothing else is using.
    """
    speaker = FakeSpeaker()
    # A shade too long for its slot: the kind of line that used to be read
    # faster when there was a clear five seconds of silence in front of it.
    cues = (cue(1, 0.0, 1.0, "short"), cue(2, 6.0, 7.0, "a line too long"))
    squeezed = speaker.fit("a line too long", 6.0, 1.0)
    assert squeezed.compressed, "the fixture no longer needs any help"

    result = dubbing.synthesise_track(cues, speaker, 12.0, rate=16_000)
    spoken = result.utterances[1]
    assert spoken.start < 6.0, "the silence in front of it was left unused"
    assert spoken.length_scale > squeezed.length_scale, "it was rushed anyway"


def test_a_line_that_fits_is_still_left_where_it_was_said():
    """Moving those too would walk the whole dub forward for no reason, which
    is what the first version of this did."""
    cues = (cue(1, 0.0, 1.0, "short"), cue(2, 6.0, 9.0, "also short"))
    result = dubbing.synthesise_track(cues, FakeSpeaker(), 12.0, rate=16_000)
    assert result.utterances[1].start == pytest.approx(6.0)


def test_room_that_does_not_help_is_not_taken():
    """A line with nowhere to grow into stays at its own timestamp rather than
    starting early for nothing."""
    speaker = FakeSpeaker()
    crowded = "a line far too long for the moment it was given here"
    cues = (cue(1, 0.0, 5.9, "a first line that runs right up to the second"),
            cue(2, 6.0, 6.5, crowded))
    result = dubbing.synthesise_track(cues, speaker, 10.0, rate=16_000)
    second = result.utterances[1]
    first = result.utterances[0]
    assert second.start >= first.start + first.duration - 1e-6


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
    ducked = dubbing.duck(original, [(2.0, 4.0)], rate)

    under = np.abs(ducked[int(2.5 * rate):int(3.5 * rate)]).mean()
    clear = np.abs(ducked[int(7.0 * rate):int(8.0 * rate)]).mean()
    assert under < clear / 4


def test_the_original_is_not_silenced():
    """It is kept so a listener can hear who is speaking, and check a
    translation the numeric audit has flagged."""
    rate = 16_000
    original = np.ones(6 * rate, dtype=np.float32) * 0.5
    ducked = dubbing.duck(original, [(0.0, 6.0)], rate)
    assert np.abs(ducked).mean() > 0.0


def test_ducking_fades_rather_than_steps():
    rate = 16_000
    original = np.ones(10 * rate, dtype=np.float32) * 0.5
    ducked = dubbing.duck(original, [(5.0, 7.0)], rate)
    edge = np.abs(np.diff(ducked[int(4.8 * rate):int(5.2 * rate)]))
    assert edge.max() < 0.05, "a level jump is audible as a click"


def test_the_original_comes_back_up_where_the_dub_has_finished():
    """The dub is shorter than the line it translates more often than not, and
    holding the original down until the caption ends leaves dead air. Measured
    on a five-minute talk before this: twelve holes, up to 2.0 s, 13.9 s in
    all, with nothing audible in them at all."""
    rate = 16_000
    original = np.ones(10 * rate, dtype=np.float32) * 0.5
    spans = dubbing.spoken_spans([spoken(start=2.0, seconds=1.0, rate=rate)])
    ducked = dubbing.duck(original, spans, rate)

    under = np.abs(ducked[int(2.4 * rate):int(2.8 * rate)]).mean()
    after = np.abs(ducked[int(4.0 * rate):int(4.5 * rate)]).mean()
    assert under < after / 4


def test_a_breath_between_two_lines_does_not_pump_the_level():
    """Opening the original for every pause is its own fault: a half-second of
    silence between two sentences would swell and duck again."""
    rate = 16_000
    spans = dubbing.spoken_spans([
        spoken(start=0.0, seconds=1.0, rate=rate),
        spoken(start=1.4, seconds=1.0, rate=rate),
    ])
    assert spans == [(0.0, 2.4)]


def test_a_long_silence_between_lines_is_opened():
    rate = 16_000
    spans = dubbing.spoken_spans([
        spoken(start=0.0, seconds=1.0, rate=rate),
        spoken(start=4.0, seconds=1.0, rate=rate),
    ])
    assert len(spans) == 2


def test_nothing_spoken_ducks_nothing():
    assert dubbing.spoken_spans([]) == []


# -- reading a live translation out loud ---------------------------------

def test_a_line_read_on_time_leaves_nothing_to_catch_up():
    from lt_core.tts.speaker import Playback

    play = Playback()
    assert play.behind(10.0) == 0.0
    play.done(10.0, 2.0)
    assert play.behind(14.0) == 0.0


def test_a_long_line_pushes_the_next_one_late():
    """Lines are read one after another and a translation is often longer than
    what it translates, so the reading falls behind the person speaking."""
    from lt_core.tts.speaker import Playback

    play = Playback()
    play.done(10.0, 8.0)
    assert play.behind(12.0) == pytest.approx(6.0)


def test_being_behind_is_measured_in_the_session_clock_not_the_wall_clock():
    """It says how much speech there is, not how fast the machine is."""
    from lt_core.tts.speaker import Playback

    play = Playback()
    play.done(0.0, 5.0)
    play.done(1.0, 5.0)
    assert play.until == pytest.approx(10.0)


# -- resampling ----------------------------------------------------------

def test_resampling_preserves_duration():
    samples = np.sin(np.linspace(0, 100, 22_050)).astype(np.float32)
    out = resample(samples, 22_050, 16_000)
    assert out.size == pytest.approx(16_000, rel=0.02)


def test_resampling_is_a_no_op_at_the_same_rate():
    samples = np.zeros(10, dtype=np.float32)
    assert resample(samples, 16_000, 16_000) is samples


def test_two_dubbed_lines_never_sound_at_once():
    """Lines were added over each other when one ran into the next slot: 22
    overlaps, 9.7 s in all, on a 27-minute video. A line now waits."""
    import numpy as np

    from lt_core.subtitles.cues import Cue
    from lt_core.tts.dub import LINE_GAP, synthesise_track
    from lt_core.tts.speaker import Utterance

    class Slow:
        voice_name = "slow"

        def fit(self, text, start, seconds, fastest=0.84):
            length = 3.0      # always longer than its 1 s slot
            return Utterance(np.full(int(length * 1000), 0.1, dtype=np.float32), 1000,
                             start, seconds, fastest, self.voice_name)

    cues = tuple(Cue(i + 1, float(i), float(i) + 1.0, (f"строка {i}",)) for i in range(4))
    dub = synthesise_track(cues, Slow(), 20.0, rate=1000)
    spans = sorted((u.start, u.start + u.duration) for u in dub.utterances)
    for (_, end), (start, _) in zip(spans, spans[1:]):
        assert start >= end + LINE_GAP - 1e-6
    assert dub.delayed == 3
