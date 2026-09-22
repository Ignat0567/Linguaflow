"""Translating a recorded video ahead: lines on the video's own clock."""

from __future__ import annotations

import threading
import time

import pytest

from lt_ui.ahead import CueVoice, Line, Track


def _track() -> Track:
    return Track([
        Line(1.0, 3.0, "Hallo zusammen.", "Всем привет."),
        Line(4.0, 6.0, "Heute geht es um Tracing.", "Сегодня речь о трассировке."),
        Line(10.0, 12.0, "Danke.", "Спасибо."),
    ], language="de")


def test_the_line_on_screen_is_the_one_at_the_video_time():
    track = _track()
    assert track.at(0.5) is None
    assert track.at(1.5).translated == "Всем привет."
    assert track.at(3.5) is None, "between lines, nothing"
    assert track.at(11.0).translated == "Спасибо."
    assert track.next_from(3.5) == 1


class _Clock:
    def __init__(self) -> None:
        self.moment = 0.0
        self.playing = True
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.moment, self.playing

    def set(self, moment: float, playing: bool = True) -> None:
        with self.lock:
            self.moment, self.playing = moment, playing


def _voice(track, clock):
    """A voice whose 'samples' are the line's text, so what was played is
    what was said, and when."""
    said: list[tuple[str, float]] = []
    voice = CueVoice(track, clock, synth=lambda line: (line.translated, 16_000),
                     play=lambda text, rate: said.append((text, clock()[0])))
    return voice, said


def _run_until(condition, seconds=2.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not condition():
        time.sleep(0.01)


def test_a_line_is_spoken_when_the_video_reaches_it_not_before():
    track, clock = _track(), _Clock()
    voice, said = _voice(track, clock)
    clock.set(0.5)
    voice.start()
    time.sleep(0.15)
    assert said == [], "nothing is said before its time"
    clock.set(1.05)
    _run_until(lambda: said)
    voice.stop()
    voice.join()
    assert said[0][0] == "Всем привет."
    assert said[0][1] >= 1.0


def test_nothing_is_spoken_while_the_video_is_paused():
    track, clock = _track(), _Clock()
    voice, said = _voice(track, clock)
    clock.set(1.2, playing=False)
    voice.start()
    time.sleep(0.2)
    assert said == []
    clock.set(1.2, playing=True)
    _run_until(lambda: said)
    voice.stop()
    voice.join()
    assert [text for text, _ in said] == ["Всем привет."]


def test_a_seek_forward_skips_what_it_jumped_over():
    """Reading a line from half a minute ago over what is being said now is
    worse than not reading it."""
    track, clock = _track(), _Clock()
    voice, said = _voice(track, clock)
    clock.set(0.0)
    voice.start()
    time.sleep(0.1)
    clock.set(10.2)
    _run_until(lambda: said)
    voice.stop()
    voice.join()
    assert [text for text, _ in said] == ["Спасибо."]


def test_a_seek_back_reads_the_lines_again():
    track, clock = _track(), _Clock()
    voice, said = _voice(track, clock)
    clock.set(4.1)
    voice.start()
    _run_until(lambda: said)
    clock.set(1.1)
    _run_until(lambda: len(said) >= 2)
    voice.stop()
    voice.join()
    assert [text for text, _ in said][:2] == ["Сегодня речь о трассировке.", "Всем привет."]


def test_a_line_passed_long_ago_is_not_read_late():
    track, clock = _track(), _Clock()
    voice, said = _voice(track, clock)
    clock.set(1.0 + CueVoice.LATE + 0.5)  # past line one's grace, before line two
    voice.start()
    time.sleep(0.2)
    voice.stop()
    voice.join()
    assert said == []


def test_the_next_lines_are_made_before_they_are_needed():
    track, clock = _track(), _Clock()
    made: list[str] = []

    def synth(line):
        made.append(line.translated)
        return (line.translated, 16_000)

    voice = CueVoice(track, clock, synth=synth, play=lambda *a: None)
    clock.set(0.0)
    voice.start()
    _run_until(lambda: len(made) >= 3)
    voice.stop()
    voice.join()
    assert made[:3] == [line.translated for line in track.lines]


def test_every_line_announces_its_start_and_end():
    track, clock = _track(), _Clock()
    heard: list[bool] = []
    voice = CueVoice(track, clock, synth=lambda line: (line.translated, 16_000),
                     play=lambda *a: None, announce=heard.append)
    clock.set(1.05)
    voice.start()
    _run_until(lambda: len(heard) >= 2)
    voice.stop()
    voice.join()
    assert heard[:2] == [True, False]


def test_the_pipeline_result_becomes_a_track_with_originals():
    from types import SimpleNamespace

    from lt_core.subtitles.cues import Cue
    from lt_ui.ahead import track_from_result

    result = SimpleNamespace(
        cues=(Cue(1, 0.0, 2.0, ("Hallo",)), Cue(2, 2.0, 4.0, ("zusammen.",))),
        translated_cues=(Cue(1, 0.0, 4.0, ("Всем привет.",)),),
        transcript=SimpleNamespace(language="de"),
    )
    track = track_from_result(result)
    assert len(track) == 1
    assert track.lines[0].translated == "Всем привет."
    assert track.lines[0].original == "Hallo zusammen."
    assert track.language == "de"


@pytest.mark.parametrize("url,video", [
    ("https://www.youtube.com/watch?v=zzOlFH0iD0k", "zzOlFH0iD0k"),
    ("https://www.youtube.com/watch?v=zzOlFH0iD0k&t=42s", "zzOlFH0iD0k"),
    ("https://youtu.be/zzOlFH0iD0k", "zzOlFH0iD0k"),
    ("https://www.youtube.com/shorts/abcDEF12345", "abcDEF12345"),
    ("https://www.youtube.com/", ""),
    ("https://www.youtube.com/@channel/live", ""),
    ("https://x.com/a/status/1", ""),
])
def test_only_a_recorded_youtube_video_is_translated_ahead(url, video):
    from PySide6.QtCore import QUrl

    from lt_ui.browser import recorded_video_id

    assert recorded_video_id(QUrl(url)) == video


def test_moving_to_another_video_stops_the_translation(tmp_path):
    """Lines made for one video must never be read over another."""
    import sys

    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication(sys.argv)
    from lt_ui.store import Store
    from lt_ui.window import Window

    window = Window(Store(tmp_path))
    screen = window._browser
    screen._ensure_view()
    screen._ahead_url = QUrl("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    screen._ahead_id = "aaaaaaaaaaa"
    screen._track = _track()
    screen._show_url(QUrl("https://www.youtube.com/watch?v=aaaaaaaaaaa&t=5s"))
    assert screen._track is not None, "the same video at another time is not a change"
    screen._show_url(QUrl("https://www.youtube.com/watch?v=bbbbbbbbbbb"))
    assert screen._track is None and screen._ahead_url is None
    window.close()


def test_the_browser_translates_into_its_own_language_not_the_live_screens(tmp_path):
    """Measured: with the Live screen at «ru -> en», a video was «translated»
    into English -- the settings' clamp saw the browser's «-> ru» beside the
    Live screen's «ru ->» and put English back on every save."""
    from lt_ui.store import Store

    store = Store(tmp_path)
    store.settings.from_lang, store.settings.to_lang = "ru", "en"
    store.settings.browser_to_lang = "ru"
    store.save_settings()
    again = Store(tmp_path)
    assert (again.settings.from_lang, again.settings.to_lang) == ("ru", "en")
    assert again.settings.browser_to_lang == "ru"
    assert again.settings.browser_from_lang == "auto"


def test_the_voice_reads_sentences_not_screen_lines():
    """Heard on a Langfuse talk: «…или нуждаетесь в более» and «эффективной
    совместной работе…» were read as two sentences, the pitch falling on
    «более» in the middle of one."""
    from lt_ui.ahead import speech_lines

    track = Track([
        Line(37.4, 40.4, "If you struggle with", "Если вы нуждаетесь в более"),
        Line(40.4, 42.0, "collaborating,", "эффективной совместной работе,"),
        Line(42.1, 44.4, "Langfuse will help.", "Langfuse поможет."),
        Line(44.7, 48.3, "All of it is open.", "Всё это открыто."),
    ])
    spoken = speech_lines(track)
    assert [line.translated for line in spoken] == [
        "Если вы нуждаетесь в более эффективной совместной работе, Langfuse поможет.",
        "Всё это открыто.",
    ]
    assert (spoken[0].start, spoken[0].end) == (37.4, 44.4)


def test_a_long_pause_ends_a_sentence_without_a_full_stop():
    from lt_ui.ahead import SENTENCE_PAUSE, speech_lines

    track = Track([
        Line(0.0, 2.0, "and so", "и вот"),
        Line(2.0 + SENTENCE_PAUSE + 1.0, 5.0, "next", "дальше."),
    ])
    assert len(speech_lines(track)) == 2


def test_a_late_sentence_is_still_read_while_its_moment_lasts():
    """Russian runs longer than English; the next sentence often starts a
    little late. Dropping it for that would silence half a talk."""
    track = Track([Line(10.0, 20.0, "long", "длинное предложение.")])
    clock = _Clock()
    voice, said = _voice(track, clock)
    clock.set(13.0)  # three seconds late, seven still to go
    voice.start()
    _run_until(lambda: said)
    voice.stop()
    voice.join()
    assert [text for text, _ in said] == ["длинное предложение."]


# -- a woman in the video is read by a woman ---------------------------------

def test_a_sentence_is_not_carried_across_to_the_other_speaker():
    from lt_ui.ahead import Line, Track, speech_lines

    track = Track([
        Line(0.0, 2.0, "So what do you", "Так что вы", "female"),
        Line(2.1, 4.0, "think about it", "об этом думаете", "female"),
        Line(4.2, 6.0, "I think that", "Я думаю, что", "male"),
    ])
    joined = speech_lines(track)
    assert [(line.voice, line.translated) for line in joined] == [
        ("female", "Так что вы об этом думаете"),
        ("male", "Я думаю, что"),
    ]


def test_the_browser_reads_with_the_same_pair_as_the_file_dub():
    from lt_ui.screens.browser import voice_names

    russian = voice_names("ru")
    # Chosen by ear on a real video: ruslan, and terra over irina.
    assert russian["male"] == "ru_RU-ruslan-medium"
    assert russian["female"] == "ru_RU-terra5871-medium"
    english = voice_names("en")
    assert english["male"] == "en_US-hfc_male-medium"
    assert english["female"] == "en_US-lessac-medium"
    # A language with one voice reads everyone with it.
    assert set(voice_names("fr")) == {""}
