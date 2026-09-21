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
    assert window._stack.currentIndex() == 0
    window.goto("settings")
    assert window._stack.currentIndex() == 4
    window.goto("history")
    assert window._stack.currentIndex() == 3
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
    QApplication.processEvents()
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
    QApplication.processEvents()
    title = window._home._title
    sub = window._home._sub
    assert abs(title.geometry().center().x() - sub.geometry().center().x()) <= 2
    window.close()


def test_file_mode_defaults_to_detecting_the_source_language():
    settings = Settings()
    assert settings.detect_language is True


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
