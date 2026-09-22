"""Day 2: cue construction and export."""

from __future__ import annotations

import json

import pytest

from lt_core.asr.types import Segment, Transcript, Word
from lt_core.subtitles.cues import CueStyle, build_cues
from lt_core.subtitles.export import (
    format_srt_time,
    format_vtt_time,
    to_json,
    to_srt,
    to_text,
    to_vtt,
    write,
)


def words(spec: list[tuple[str, float, float]]) -> tuple[Word, ...]:
    return tuple(Word(text=t, start=s, end=e) for t, s, e in spec)


def transcript(segments: list[Segment], language: str = "en") -> Transcript:
    end = max((s.end for s in segments), default=0.0)
    return Transcript(
        segments=tuple(segments), language=language,
        language_probability=1.0, duration=end,
    )


def sentence(text: str, start: float, pace: float = 0.4, language: str = "en"):
    """Build a segment whose words are evenly spaced."""
    tokens = text.split(" ")
    built = []
    clock = start
    for token in tokens:
        built.append((" " + token, clock, clock + pace))
        clock += pace
    return Segment(text=text, start=start, end=clock, words=words(built))


# -- time formatting -----------------------------------------------------

def test_srt_time_uses_a_comma():
    assert format_srt_time(3661.5) == "01:01:01,500"


def test_vtt_time_uses_a_period():
    """WebVTT rejects the comma SRT requires; players show nothing at all."""
    assert format_vtt_time(3661.5) == "01:01:01.500"


def test_time_never_goes_negative():
    assert format_srt_time(-5.0) == "00:00:00,000"


def test_time_rounds_rather_than_truncates():
    assert format_srt_time(1.9999) == "00:00:02,000"


# -- cue construction ----------------------------------------------------

def test_long_segment_becomes_several_cues():
    """A 30-second segment is not a subtitle."""
    text = " ".join(["word"] * 60)
    result = build_cues(transcript([sentence(text, 0.0)]))
    assert len(result) > 1
    assert all(sum(len(line) for line in cue.lines) <= CueStyle().max_chars
               for cue in result)


def test_no_line_exceeds_the_width_limit():
    text = " ".join(f"token{n}" for n in range(40))
    for cue in build_cues(transcript([sentence(text, 0.0)])):
        for line in cue.lines:
            assert len(line) <= CueStyle().max_chars_per_line


def test_cue_never_shorter_than_the_minimum():
    result = build_cues(transcript([sentence("Yes.", 0.0, pace=0.05)]))
    assert all(cue.duration >= CueStyle().min_duration - 1e-6 for cue in result)


def test_cues_do_not_overlap():
    text = " ".join(["alpha beta gamma delta."] * 8)
    result = build_cues(transcript([sentence(text, 0.0)]))
    for earlier, later in zip(result, result[1:]):
        assert later.start >= earlier.end


def test_a_word_stretched_across_a_pause_is_not_a_thirteen_second_cue():
    """Real German lecture: Whisper timed 'eine' at 13.3 s and 'schlechte'
    at another 13.3 s, so four one-word cues for one short sentence."""
    segment = Segment(
        text="Das ist eine schlechte Bewegung.",
        start=29.22, end=59.33,
        words=words([
            (" Das", 29.22, 31.72),
            (" ist", 31.72, 31.80),
            (" eine", 31.80, 45.10),
            (" schlechte", 45.18, 58.48),
            (" Bewegung.", 58.56, 59.33),
        ]),
    )
    result = build_cues(transcript([segment], language="de"))
    assert not any(
        cue.duration > 8.0 and len(cue.flat_text.split()) == 1
        for cue in result
    ), [ (cue.flat_text, round(cue.duration, 1)) for cue in result ]
    assert "Bewegung" in " ".join(cue.flat_text for cue in result)


def test_the_same_line_said_three_times_in_a_row_is_one_cue():
    """Same lecture: 'Und dann aber auch in der Ukraine.' three times
    over 3.8 seconds."""
    line = "Und dann aber auch in der Ukraine."
    copies = [
        sentence(line, start, pace=0.15, language="de")
        for start in (222.10, 223.96, 225.80)
    ]
    result = build_cues(transcript(copies, language="de"))
    texts = [cue.flat_text.strip() for cue in result]
    assert texts.count(line) == 1


def test_original_token_spacing_is_preserved():
    """Regression: re-joining with a uniform space corrupted text.

    Whisper's tokens carry their own leading space, and its absence is
    meaningful. Stripping and re-joining turned "$12,000" into "$12 ,000" and
    "real-time" into "real -time" in every exported file.
    """
    segment = Segment(
        text="costs $12,000 per real-time run",
        start=0.0, end=2.5,
        words=words([
            (" costs", 0.0, 0.5), (" $12", 0.5, 1.0), (",000", 1.0, 1.2),
            (" per", 1.2, 1.5), (" real", 1.5, 1.9), ("-time", 1.9, 2.1),
            (" run", 2.1, 2.5),
        ]),
    )
    text = build_cues(transcript([segment]))[0].flat_text
    assert "$12,000" in text
    assert "real-time" in text
    assert " ,000" not in text and " -time" not in text


def test_a_cue_never_ends_in_the_middle_of_a_word():
    """Regression, from a real five-minute talk.

    The tokens are Whisper's own: it emits "self-improvement" as " self" and
    "-improvement,", and only the missing leading space says they are one word.
    The cue boundary landed between them, so the viewer read "...to commit to a
    policy of self" and then "-improvement, self-change."

    The timings are the measured ones, because the break is the product of the
    7-second cue limit falling exactly there.
    """
    spoken = [
        (" To", 207.83, 208.27), (" say", 208.27, 208.45),
        (" you", 208.45, 208.61), (" are", 208.61, 208.75),
        (" wrong", 208.75, 209.33), (" is", 209.33, 209.73),
        (" also", 209.73, 210.13), (" to", 210.13, 210.41),
        (" commit", 210.41, 210.87), (" to", 210.87, 211.79),
        (" a", 211.79, 212.03), (" policy", 212.03, 212.61),
        (" of", 212.61, 213.57), (" self", 213.57, 213.89),
        ("-improvement,", 213.89, 214.49), (" self", 214.65, 215.19),
        ("-change.", 215.19, 215.71),
    ]
    segment = Segment(
        text="To say you are wrong is also to commit to a policy of"
             " self-improvement, self-change.",
        start=207.83, end=215.71, words=words(spoken),
    )
    result = build_cues(transcript([segment]))
    assert len(result) > 1, "the fixture must be long enough to be split"
    for cue in result:
        assert not cue.flat_text.startswith("-"), cue.flat_text
        assert not cue.flat_text.endswith("self"), cue.flat_text
    assert any("self-improvement" in cue.flat_text for cue in result)


def test_cues_ignore_whisper_segment_boundaries():
    """Regression: the model's window boundaries fell mid-phrase.

    On the reference clip five of eight segments ended on a word like "per" or
    "the", with a 0.00 s gap to the next. Honouring them as cue boundaries
    stamped every one into the subtitles. Only a real pause may end a cue.
    """
    first = Segment(
        text="and cut spending by roughly twelve thousand per",
        start=0.0, end=2.8,
        words=words([
            (" and", 0.0, 0.4), (" cut", 0.4, 0.8), (" spending", 0.8, 1.2),
            (" by", 1.2, 1.6), (" roughly", 1.6, 2.0), (" twelve", 2.0, 2.4),
            (" per", 2.4, 2.8),
        ]),
    )
    # Starts exactly where the previous ended: no pause, no reason to break.
    second = Segment(
        text="month.", start=2.8, end=3.2,
        words=words([(" month.", 2.8, 3.2)]),
    )
    result = build_cues(transcript([first, second]))
    assert any("per month." in cue.flat_text for cue in result)


def test_a_real_pause_still_ends_a_cue():
    first = sentence("Good morning everyone", 0.0)
    second = sentence("and welcome to the review", 5.0)
    result = build_cues(transcript([first, second]))
    assert len(result) >= 2


def test_cue_does_not_end_on_a_dangling_preposition():
    text = ("we reduced the average response latency of the authentication "
            "service by roughly thirty one percent overall")
    result = build_cues(transcript([sentence(text, 0.0)]))
    for cue in result[:-1]:
        last = cue.flat_text.split()[-1].strip(".,").lower()
        assert last not in {"of", "by", "the", "to", "for"}


def test_short_fragment_is_merged_into_its_neighbour():
    """A two-word flash followed by its own sentence reads as a stutter."""
    first = Segment(text="Guten Morgen,", start=0.0, end=0.7,
                    words=words([(" Guten", 0.0, 0.35), (" Morgen,", 0.35, 0.7)]))
    second = sentence("vielen Dank fuer Ihre Teilnahme", 1.3)
    result = build_cues(transcript([first, second], language="de"))
    assert result[0].flat_text.startswith("Guten Morgen, vielen")


def test_merge_is_refused_across_a_long_silence():
    first = Segment(text="Hello.", start=0.0, end=0.5,
                    words=words([(" Hello.", 0.0, 0.5)]))
    second = sentence("And now for something completely different", 30.0)
    result = build_cues(transcript([first, second]))
    assert result[0].flat_text == "Hello."


# -- CJK -----------------------------------------------------------------

def test_cjk_style_differs_from_latin():
    assert CueStyle.for_language("zh").max_chars_per_line < CueStyle().max_chars_per_line
    assert CueStyle.for_language("ja").join_with_space is False
    assert CueStyle.for_language("fr").join_with_space is True


def test_cjk_wrapping_never_splits_a_number():
    """Regression: a fixed-width slice cut "31%" into "3" and "1%".

    The same class of corruption as the spacing bug, one layer further on: the
    text was right and the line break destroyed it.
    """
    from lt_core.subtitles.cues import _wrap_without_spaces

    style = CueStyle.for_language("ja")
    lines = _wrap_without_spaces("私たちのチームは平均応答遅延を31%削減しました。", style)
    assert any("31%" in line for line in lines)
    assert not any(line.endswith("3") for line in lines)


def test_cjk_wrapping_loses_nothing():
    from lt_core.subtitles.cues import _wrap_without_spaces

    style = CueStyle.for_language("zh")
    text = "我们的团队减少了31%的平均响应延迟，还削减了每月12000美元的支出。"
    assert "".join(_wrap_without_spaces(text, style)) == text


def test_cjk_lines_are_balanced():
    """16/3 and 10/9 hold the same text; only one of them reads."""
    from lt_core.subtitles.cues import _wrap_without_spaces

    style = CueStyle.for_language("zh")
    lines = _wrap_without_spaces("大家早上好感谢各位参加本次季度回顾会议", style)
    assert len(lines) == 2
    assert abs(len(lines[0]) - len(lines[1])) <= 3


def test_cjk_prefers_breaking_after_punctuation():
    from lt_core.subtitles.cues import _wrap_without_spaces

    style = CueStyle.for_language("ja")
    lines = _wrap_without_spaces(
        "皆さん、おはようございます。私たちのチームは削減しました。", style)
    assert lines[0].endswith("。")


# -- export --------------------------------------------------------------

def test_srt_structure():
    result = build_cues(transcript([sentence("Hello there friend", 0.0)]))
    body = to_srt(result)
    assert body.startswith("1\n")
    assert " --> " in body
    assert body.endswith("\n")


def test_srt_numbers_cues_from_one_without_gaps():
    text = " ".join(["alpha beta gamma delta epsilon."] * 6)
    body = to_srt(build_cues(transcript([sentence(text, 0.0)])))
    numbers = [
        int(line) for line in body.splitlines()
        if line.strip().isdigit() and "-->" not in line
    ]
    assert numbers == list(range(1, len(numbers) + 1))


def test_vtt_starts_with_its_signature():
    """A WebVTT file without the header is rejected outright by browsers."""
    result = build_cues(transcript([sentence("Hello there", 0.0)]))
    assert to_vtt(result).startswith("WEBVTT\n\n")


def test_text_export_has_no_timings():
    body = to_text(transcript([sentence("Hello there friend", 0.0)]))
    assert "-->" not in body and "00:00" not in body


def test_text_export_with_timestamps():
    body = to_text(transcript([sentence("Hello there", 0.0)]), timestamps=True)
    assert body.startswith("[00:00:00]")


def test_json_round_trips():
    source = transcript([sentence("Hello there friend", 0.0)])
    payload = json.loads(to_json(source, build_cues(source)))
    assert payload["language"] == "en"
    assert payload["segments"][0]["words"][0]["text"] == "Hello"
    assert payload["cues"][0]["lines"]


def test_written_files_carry_no_bom(tmp_path):
    """A BOM makes ffmpeg and most web players reject the first cue."""
    path = write(tmp_path / "out.srt", "1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw


def test_written_files_use_utf8(tmp_path):
    path = write(tmp_path / "out.srt", "Grüße, 皆さん\n")
    assert path.read_text(encoding="utf-8") == "Grüße, 皆さん\n"


def test_unknown_format_is_rejected_before_any_work():
    from lt_core.subtitles.export import EXPORTERS

    assert "srt" in EXPORTERS and "vtt" in EXPORTERS
    assert "docx" not in EXPORTERS


@pytest.mark.parametrize("language", ["en", "de", "ru", "es", "it", "fr"])
def test_latin_languages_share_the_default_style(language):
    assert CueStyle.for_language(language) == CueStyle()
