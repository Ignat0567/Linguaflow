"""The ring after recognition.

Recognition used to be mapped onto four fifths of the ring and everything
after it — translation, a synthesis pass per line, the dub, the video —
reported nothing until the job returned. On a long recording that tail is
the long part, and a ring parked at 80% reads as a hang. The shares below
are not a forecast of minutes. They exist so the ring moves when a stage
moves, and so a stage that will not run does not leave a gap.
"""

from __future__ import annotations

import wave

import numpy as np
import pytest

from lt_core.asr.types import Segment, Transcript, Word
from lt_core.pipeline.batch import (
    _Meter,
    progress_plan,
    recognition_mark,
    transcribe_file,
)


def test_a_dub_keeps_four_fifths_for_recognition_and_room_after_it():
    phases = progress_plan(
        translate=True, voice=True, condense=True, shorten=True, video=True,
    )
    by_name = {name: (start, end) for name, start, end in phases}
    assert by_name["recognize"] == (0.0, recognition_mark(voice=True))
    assert by_name["recognize"][1] == pytest.approx(0.80)
    assert by_name["mux"][1] == pytest.approx(0.99)
    assert by_name["speak"][1] > by_name["condense"][1] > 0.80
    cursor = 0.0
    for _name, start, end in phases:
        assert start == pytest.approx(cursor)
        assert end > start
        cursor = end


def test_a_stage_that_will_not_run_is_not_given_a_band():
    """A band reserved for a voice nobody asked for sits still, which is
    the freeze the plan is there to remove."""
    names = [
        name for name, _start, _end in progress_plan(
            translate=True, voice=False, condense=True, shorten=True, video=True,
        )
    ]
    assert names == ["recognize", "translate"]
    assert recognition_mark(voice=False) == pytest.approx(0.92)


def test_a_plain_transcript_fills_the_ring_up_to_the_result():
    assert progress_plan(
        translate=False, voice=False, condense=False, shorten=False, video=False,
    ) == (("recognize", 0.0, 0.99),)


def test_skipping_a_finished_stage_does_not_walk_the_ring_backwards():
    seen: list[float] = []
    meter = _Meter(progress_plan(
        translate=True, voice=True, condense=True, shorten=False, video=True,
    ), seen.append)
    meter.enter("recognize")
    meter.advance(1, 2)
    assert seen[-1] == pytest.approx(0.40)
    meter.advance(2, 2)
    meter.leave()
    assert seen[-1] == pytest.approx(0.80)
    meter.skip("translate", "condense", "speak", "mux")
    assert seen[-1] == pytest.approx(0.99)
    assert all(later >= earlier for earlier, later in zip(seen, seen[1:]))


def test_half_a_stage_lands_inside_that_stage():
    seen: list[float] = []
    meter = _Meter(progress_plan(
        translate=True, voice=True, condense=True, shorten=True, video=False,
    ), seen.append)
    meter.enter("speak")
    start = seen[-1]
    meter.advance_within(0.0, 0.5, 1, 1)
    assert start < seen[-1]
    meter.advance(1, 2)
    # The whole-stage advance and the half-band one share the same span,
    # and neither may leave it.
    _name, lo, hi = next(
        phase for phase in progress_plan(
            translate=True, voice=True, condense=True, shorten=True, video=False,
        )
        if phase[0] == "speak"
    )
    assert lo <= seen[-1] <= hi
    meter.leave()
    assert seen[-1] == pytest.approx(0.99)


def _wav(path, seconds: float = 1.0, rate: int = 16_000) -> None:
    samples = np.zeros(int(seconds * rate), dtype=np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())


class _Transcriber:
    def transcribe(self, path, options=None, on_progress=None, total_duration=None):
        if on_progress is not None and total_duration:
            on_progress(total_duration / 2, total_duration)
        word = Word("Hello", 0.0, 0.4)
        return Transcript(
            segments=(Segment("Hello.", 0.0, 0.5, words=(word,)),),
            language="en",
            language_probability=0.99,
            duration=total_duration or 1.0,
        )


class _Translator:
    def __init__(self) -> None:
        self.seen = 0

    def translate(self, texts, source, target):
        self.seen += 1
        return [f"{target}: {text}" for text in texts], None


def test_a_transcript_reports_seconds_and_a_fraction_up_to_the_result(tmp_path):
    """The command line's bar is still seconds of audio. The ring is not."""
    path = tmp_path / "clip.wav"
    _wav(path)
    seconds: list[tuple[float, float]] = []
    fractions: list[float] = []
    translator = _Translator()

    transcribe_file(
        path,
        _Transcriber(),
        output_dir=tmp_path,
        on_progress=lambda done, total: seconds.append((done, total)),
        on_fraction=fractions.append,
        translator=translator,
        target_language="ru",
        voice=False,
    )

    assert translator.seen == 1
    assert seconds and seconds[-1][0] == pytest.approx(seconds[-1][1])
    assert seconds[-1][1] > 0.5
    assert any(value == pytest.approx(0.46) for value in fractions)
    assert any(value == pytest.approx(recognition_mark(voice=False)) for value in fractions)
    assert fractions[-1] == pytest.approx(0.99)
    assert fractions[-1] < 1.0
    assert all(later >= earlier for earlier, later in zip(fractions, fractions[1:]))


def test_the_same_language_closes_the_later_stages_without_translating(tmp_path):
    path = tmp_path / "clip.wav"
    _wav(path)
    fractions: list[float] = []
    translator = _Translator()

    class SameLanguage(_Transcriber):
        def transcribe(self, path, options=None, on_progress=None, total_duration=None):
            transcript = super().transcribe(path, options, on_progress, total_duration)
            return Transcript(
                segments=transcript.segments,
                language="ru",
                language_probability=1.0,
                duration=transcript.duration,
            )

    transcribe_file(
        path,
        SameLanguage(),
        output_dir=tmp_path,
        on_fraction=fractions.append,
        translator=translator,
        target_language="ru",
        voice=True,
        dub_video=True,
    )

    assert translator.seen == 0
    assert fractions[-1] == pytest.approx(0.99)
    assert all(later >= earlier for earlier, later in zip(fractions, fractions[1:]))
