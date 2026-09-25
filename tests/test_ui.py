"""Day 6: settings, history, and the window that shows them."""

from __future__ import annotations

import os

import pytest

from lt_core.mt.types import TranslationMode
from lt_ui.store import (
    HistoryEntry,
    Settings,
    Store,
    display_name,
    format_clock,
    format_date,
    new_id,
)


# -- store ---------------------------------------------------------------

def test_defaults_are_offline_russian_to_english():
    settings = Settings()
    settings.clamp()
    assert settings.from_lang == "ru"
    assert settings.to_lang == "en"
    assert settings.translation_mode == TranslationMode.OFFLINE


def test_clamp_drops_a_language_this_build_does_not_offer():
    settings = Settings(from_lang="zh", to_lang="ja")
    settings.clamp()
    assert settings.from_lang in settings.offered()
    assert settings.to_lang in settings.offered()
    assert settings.from_lang != settings.to_lang


def test_setting_from_to_the_same_language_swaps_the_other_side():
    settings = Settings(from_lang="ru", to_lang="en")
    settings.set_from("en")
    assert settings.from_lang == "en"
    assert settings.to_lang == "ru"


def test_swap_exchanges_the_pair():
    settings = Settings(from_lang="de", to_lang="ru")
    settings.swap()
    assert settings.from_lang == "ru"
    assert settings.to_lang == "de"


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path)
    store.settings.from_lang = "de"
    store.settings.to_lang = "en"
    store.settings.voiceover = False
    store.settings.translation_mode = TranslationMode.ONLINE
    store.settings.online_service = "groq"
    store.settings.overlay = False
    store.settings.overlay_hidden_from_share = False
    store.settings.detect_language = False
    store.save_settings()

    store.add(HistoryEntry(
        id="abc", kind="file", title="talk.mp3",
        source_language="en", target_language="de",
        duration=94, created="2026-09-17T12:00:00",
        folder=str(tmp_path / "jobs" / "abc"),
        outputs={"srt": "talk.srt"},
    ))

    again = Store(tmp_path)
    assert again.settings.from_lang == "de"
    assert again.settings.voiceover is False
    assert again.settings.online_service == "groq"
    assert again.settings.overlay is False
    assert again.settings.overlay_hidden_from_share is False
    assert again.settings.detect_language is False
    assert len(again.entries) == 1
    assert again.entries[0].title == "talk.mp3"
    assert again.recent(3)[0].id == "abc"


def test_corrupt_settings_file_does_not_crash(tmp_path):
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    store = Store(tmp_path)
    assert store.settings.from_lang == "ru"


def test_a_settings_file_with_a_byte_order_mark_is_still_read(tmp_path):
    """Windows PowerShell and older Notepad save one. It used to reset every
    setting to its default without a word."""
    (tmp_path / "settings.json").write_text(
        '{"ui_language": "de", "to_lang": "de"}', encoding="utf-8-sig"
    )
    store = Store(tmp_path)
    assert store.settings.ui_language == "de"
    assert store.settings.to_lang == "de"


def test_an_unreadable_file_is_kept_aside_not_saved_over(tmp_path):
    (tmp_path / "history.json").write_text('[{"id": "a", "tit', encoding="utf-8")
    store = Store(tmp_path)
    assert store.entries == []
    store.add(HistoryEntry(
        id="b", kind="live", title="new", source_language="ru",
        target_language="en", duration=1, created="2026-09-25T12:00:00",
    ))
    kept = tmp_path / "history.json.unreadable"
    assert kept.read_text(encoding="utf-8") == '[{"id": "a", "tit'


def test_settings_of_the_wrong_shape_do_not_stop_the_app(tmp_path):
    (tmp_path / "settings.json").write_text("[]", encoding="utf-8")
    (tmp_path / "history.json").write_text("{}", encoding="utf-8")
    store = Store(tmp_path)
    assert store.settings.from_lang == "ru"
    assert store.entries == []


def test_a_save_replaces_the_file_whole(tmp_path, monkeypatch):
    """A save that fails halfway must leave the previous file as it was."""
    import json

    from lt_ui import store as store_module

    store = Store(tmp_path)
    store.settings.to_lang = "de"
    store.save_settings()

    def full_disk(*args, **kwargs):
        raise OSError("No space left on device")

    store.settings.to_lang = "en"
    monkeypatch.setattr(store_module.os, "replace", full_disk)
    with pytest.raises(OSError):
        store.save_settings()
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["to_lang"] == "de"


def test_recent_is_newest_first_and_capped(tmp_path):
    store = Store(tmp_path)
    for n in range(5):
        store.add(HistoryEntry(
            id=str(n), kind="live", title=f"c{n}",
            source_language="ru", target_language="en",
            duration=1, created="2026-09-17T12:00:00",
        ))
    recent = store.recent(3)
    assert [row.id for row in recent] == ["4", "3", "2"]


def test_display_name_is_capitalised():
    assert display_name("ru") == "Русский"
    assert display_name("en") == "Английский"


def test_format_clock_hides_hours_until_needed():
    assert format_clock(94) == "01:34"
    assert format_clock(3723) == "1:02:03"


def test_format_date_uses_russian_months():
    from lt_ui import i18n

    i18n.set_language("ru")
    assert format_date("2026-09-17T12:04:00") == "17 сент 2026"


def test_format_date_follows_the_interface_language():
    from lt_ui import i18n

    i18n.set_language("de")
    assert format_date("2026-09-17T12:04:00") == "17. Sept. 2026"
    i18n.set_language("en")
    assert format_date("2026-09-17T12:04:00") == "17 Sept 2026"
    i18n.set_language("ru")


def test_new_ids_are_unique():
    assert new_id() != new_id()


# -- widgets, offscreen --------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["linguaflow-tests"])
    yield app


def test_a_live_caption_shows_the_draft_translation_under_the_settled_one(qapp):
    """While a sentence is still being spoken its translation is provisional.
    It is drawn in a lighter hand, below the settled text, and it must not
    replace it: both are true at once for as long as the sentence lasts."""
    from lt_ui.screens.realtime import Line, _Caption

    line = Line(
        original="Good morning everyone.", translated="Доброе утро всем.",
        partial_translated="За последние три месяца",
    )
    from PySide6.QtWidgets import QLabel

    caption = _Caption(line, conversation=False)
    shown = [label.text() for label in caption.findChildren(QLabel)]
    assert any("Доброе утро" in text for text in shown), shown
    assert any("За последние" in text for text in shown), shown


def test_a_caption_with_only_a_draft_translation_still_draws(qapp):
    from lt_ui.screens.realtime import Line, _Caption

    _Caption(Line(partial_translated="черновик"), conversation=False)


def test_language_pair_auto_does_not_collide_with_the_target(qapp):
    from lt_ui.widgets import LanguagePair

    pair = LanguagePair(allow_auto=True)
    pair.set_pair("auto", "en")
    source, target = pair.pair()
    assert source == "auto"
    assert target == "en"
    pair._to.setCurrentIndex(pair._to.findData("ru"))
    source, target = pair.pair()
    assert source == "auto"
    assert target == "ru"


def test_language_pair_refuses_identical_sides(qapp, tmp_path):
    from lt_ui.widgets import LanguagePair

    pair = LanguagePair()
    pair.set_pair("ru", "en")
    # Choose the current target as the new source: the other side must move.
    pair._from.setCurrentIndex(pair._from.findData("en"))
    source, target = pair.pair()
    assert source == "en"
    assert target != "en"


def test_chip_group_is_exclusive(qapp):
    from lt_ui.widgets import ChipGroup

    group = ChipGroup((("a", "A"), ("b", "B"), ("c", "C")))
    group.set_value("b")
    assert group.value() == "b"
    group.set_value("c")
    assert group.value() == "c"
    checked = [btn.isChecked() for btn in group._group.buttons()]
    assert sum(checked) == 1


def test_window_opens_on_home_and_nav_switches(qapp, tmp_path):
    from lt_ui.window import Window
    from lt_ui.store import Store

    window = Window(Store(tmp_path))
    window.resize(960, 640)
    assert window.current_screen == "home"
    window.goto("settings")
    assert window.current_screen == "settings"
    window.goto("history")
    assert window.current_screen == "history"
    window.close()


def test_settings_screen_writes_through_the_store(qapp, tmp_path):
    from lt_ui.window import Window
    from lt_ui.store import Store

    store = Store(tmp_path)
    window = Window(store)
    window.goto("settings")
    window._settings._voice.setChecked(False)
    group = window._settings._format
    group._group.button(group._keys.index("vtt")).click()
    again = Store(tmp_path)
    assert again.settings.voiceover is False
    assert again.settings.sub_format == "vtt"
    window.close()


def test_settings_page_is_taller_than_the_window(qapp, tmp_path):
    """Capture, notifications and accent sit below the fold at 800px."""
    from PySide6.QtWidgets import QApplication
    from lt_ui.window import Window
    from lt_ui.store import Store

    window = Window(Store(tmp_path))
    window.resize(1280, 800)
    window.goto("settings")
    QApplication.sendPostedEvents()
    scroll = window._stack.currentWidget()
    assert scroll.widget().minimumSizeHint().height() > scroll.viewport().height()
    window.close()


def test_home_shows_recent_entries(qapp, tmp_path):
    from lt_ui.window import Window
    from lt_ui.store import HistoryEntry, Store

    store = Store(tmp_path)
    store.add(HistoryEntry(
        id="x", kind="file", title="lecture.m4a",
        source_language="en", target_language="ru",
        duration=453, created="2026-09-17T10:00:00",
    ))
    window = Window(store)
    window._home.refresh()
    assert window._home._recent.count() >= 1
    window.close()


def test_the_home_subtitle_sits_under_the_middle_of_the_headline(qapp, tmp_path):
    from PySide6.QtWidgets import QApplication
    from lt_ui.window import Window
    from lt_ui.store import Store

    window = Window(Store(tmp_path))
    window.resize(1280, 800)
    window.show()
    # Qt's queue is drained rather than the native event loop entered; see
    # tests.test_polish for what that is worth and what it is not.
    QApplication.sendPostedEvents()
    title = window._home._title
    sub = window._home._sub
    assert abs(title.geometry().center().x() - sub.geometry().center().x()) <= 2
    window.close()


def test_file_mode_defaults_to_detecting_the_source_language():
    settings = Settings()
    assert settings.detect_language is True


def test_a_fresh_file_pair_detects_and_keeps_the_old_target():
    settings = Settings()
    settings.clamp()
    assert settings.file_from_lang == "auto"
    assert settings.file_to_lang == settings.to_lang


def test_an_old_profile_opens_the_file_screen_the_way_it_was_left(tmp_path):
    (tmp_path / "settings.json").write_text(
        '{"from_lang": "de", "to_lang": "ru", "detect_language": false}',
        encoding="utf-8",
    )
    settings = Store(tmp_path).settings
    assert (settings.file_from_lang, settings.file_to_lang) == ("de", "ru")


def test_the_file_screen_can_translate_into_the_live_screens_language(
    qapp, tmp_path
):
    """The default live pair is Russian into English. Choosing «auto -> Russian»
    on the file screen used to be clamped back to English on save while the
    picker still showed Russian -- and an English video came out untranslated.
    """
    from lt_ui.window import Window

    store = Store(tmp_path)
    window = Window(store)
    window.goto("upload")
    pair = window._upload._idle.pair
    pair._to.setCurrentIndex(pair._to.findData("ru"))

    assert store.settings.file_to_lang == "ru"
    assert Store(tmp_path).settings.file_to_lang == "ru", "and it is saved"
    window.goto("home")
    window.goto("upload")
    assert pair.pair() == ("auto", "ru"), "and still shown on coming back"
    assert (store.settings.from_lang, store.settings.to_lang) == ("ru", "en"), (
        "the Live screen's pair is not touched"
    )
    window.close()


@pytest.mark.parametrize("source, language", [("auto", None), ("de", "de")])
def test_the_batch_job_is_given_the_file_screens_pair(
    qapp, tmp_path, monkeypatch, source, language
):
    """What the picker shows is what the job runs with."""
    from lt_ui import engine

    seen = {}

    def fake_transcribe(path, transcriber, **kwargs):
        seen["language"] = kwargs["options"].language
        seen["target"] = kwargs["target_language"]
        raise RuntimeError("stop here")

    monkeypatch.setattr(engine, "transcribe_file", fake_transcribe)
    settings = Settings(from_lang="ru", to_lang="en",
                        file_from_lang=source, file_to_lang="ru")
    worker = engine.BatchWorker(tmp_path / "clip.mp4", settings, None, None, tmp_path)
    worker.run()  # on this thread: the job itself, not the scheduling
    assert seen == {"language": language, "target": "ru"}


def test_overlay_defaults_to_hidden_from_a_screen_share():
    settings = Settings()
    assert settings.overlay is True
    assert settings.overlay_hidden_from_share is True


def test_affinity_exclude_sends_the_capture_flag():
    from lt_ui.affinity import WDA_EXCLUDEFROMCAPTURE, WDA_NONE, apply

    seen = []

    def setter(hwnd, affinity):
        seen.append((hwnd, affinity))
        return True

    assert apply(42, True, setter=setter) is True
    assert apply(42, False, setter=setter) is True
    assert seen == [(42, WDA_EXCLUDEFROMCAPTURE), (42, WDA_NONE)]


def test_affinity_without_a_window_does_not_pretend_to_work():
    from lt_ui.affinity import apply

    assert apply(0, True, setter=lambda hwnd, affinity: True) is False


def test_overlay_window_shows_translation_above_the_original(qapp, tmp_path):
    from PySide6.QtCore import Qt
    from lt_ui.overlay import OverlayWindow
    from lt_ui.store import Store

    overlay = OverlayWindow(Store(tmp_path))
    overlay.set_caption(
        original="Hello, great to see you.",
        translated="Здравствуйте, рады вас видеть.",
        speaker="English · A",
    )
    assert "Здравствуйте" in overlay._translated.text()
    assert "Hello" in overlay._original.text()
    assert overlay._speaker.isVisibleTo(overlay)
    from PySide6.QtCore import Qt

    flags = overlay.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    overlay.close()


def test_overlay_uses_the_original_until_a_translation_arrives(qapp, tmp_path):
    from lt_ui.overlay import OverlayWindow
    from lt_ui.store import Store

    overlay = OverlayWindow(Store(tmp_path))
    overlay.set_caption(original="Waiting for the other side.", translated="")
    assert "Waiting" in overlay._translated.text()
    assert overlay._original.isHidden()
    overlay.close()


def test_a_long_translation_fits_the_subtitle_window(qapp, tmp_path):
    """A long sentence at 28 px ran out of the bottom of the window."""
    from lt_ui.overlay import OverlayWindow
    from lt_ui.store import Store

    overlay = OverlayWindow(Store(tmp_path))
    overlay.reveal()
    overlay.resize(765, 190)
    long_text = " ".join(["очень длинное предложение перевода"] * 12) + " конец"
    overlay.set_caption(original="kurz", translated=long_text, listening=True)
    qapp.processEvents()
    label = overlay._translated
    try:
        assert label.full_text() == long_text
        shown = label.text()
        # What is shown fits, and it is the end of what was said.
        assert shown.startswith("…") and shown.endswith("конец")
        assert label.font().pixelSize() == label.smallest
        overlay.resize(1400, 700)
        qapp.processEvents()
        assert label.text() == long_text
    finally:
        overlay.hide()


def test_the_live_feed_follows_new_lines_unless_scrolled_up(qapp, tmp_path):
    from PySide6.QtTest import QTest

    from lt_ui.screens.realtime import Line
    from lt_ui.store import Store
    from lt_ui.window import Window

    window = Window(Store(tmp_path))
    window.resize(1280, 800)
    window.show()
    window.goto("realtime")
    screen = window._realtime
    bar = screen._scroll.verticalScrollBar()

    def add(count):
        for _ in range(count):
            screen._lines.append(Line(original="Ein langer Satz, " * 8, translated="Длинная фраза. " * 6))
        screen._render()
        QTest.qWait(250)   # the old lines go by deleteLater, the layout settles after

    try:
        add(15)
        assert bar.maximum() > 0 and bar.value() == bar.maximum()
        # The record button is not covered by the panel any more.
        assert screen._record.geometry().bottom() < screen._panel.geometry().top()
        bar.setValue(0)
        QTest.qWait(50)
        add(2)
        assert bar.value() == 0          # left where the reader put it
        bar.setValue(bar.maximum())
        QTest.qWait(50)
        add(1)
        assert bar.value() == bar.maximum()
    finally:
        window.hide()


def test_a_live_line_is_the_sentence_that_was_translated(qapp, tmp_path):
    """The screen closed its line when a translation arrived, by which time
    the next sentence's first words were in it: the line ended «...geeinigt
    haben. Das ist natürlich ein Extrem, aber es ist eigentlich bei» over the
    first sentence's translation alone, and the next began mid-sentence."""
    from lt_core.realtime.session import LiveUpdate
    from lt_ui.store import Store
    from lt_ui.window import Window

    window = Window(Store(tmp_path))
    screen = window._realtime
    screen._mine = True
    screen._on_update(LiveUpdate(committed="Wir haben uns geeinigt."))
    screen._on_update(LiveUpdate(committed="Das ist natürlich"))
    screen._on_update(LiveUpdate(
        committed="ein Extrem,", partial="aber es",
        translation="Мы договорились.", translation_source="Wir haben uns geeinigt.",
    ))
    assert [(line.original, line.translated) for line in screen._lines] == [
        ("Wir haben uns geeinigt.", "Мы договорились."),
    ]
    # What was already heard of the next sentence starts the next line.
    assert screen._current.original == "Das ist natürlich ein Extrem,"
    assert screen._current.partial == "aber es"


def test_a_translation_without_its_source_still_closes_the_line(qapp, tmp_path):
    """Conversation mode does not say what it translated: the old way."""
    from lt_core.realtime.session import LiveUpdate
    from lt_ui.store import Store
    from lt_ui.window import Window

    window = Window(Store(tmp_path))
    screen = window._realtime
    screen._mine = True
    screen._on_update(LiveUpdate(committed="Hello there.", speaker="A"))
    screen._on_update(LiveUpdate(translation="Привет.", speaker="A"))
    assert [(line.original, line.translated) for line in screen._lines] == [
        ("Hello there.", "Привет."),
    ]
