"""Day 7: the rough edges a user found by using the thing.

Four reports, each of them a small fault with a real cost: a border that
stopped short, three acronyms with nothing to tell them apart, a job that
started before it was asked to, and a list with no way to reach the files it
described or to clear itself.
"""

from __future__ import annotations

import sys
import tempfile

import pytest

from lt_ui import i18n
from lt_ui.store import HistoryEntry, Store


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUAFLOW_DATA", str(tmp_path / "profile"))
    from lt_core.runtime import bootstrap
    from lt_ui.store import MODEL_ROOT
    from lt_ui.window import Window

    bootstrap(MODEL_ROOT)
    return Window(Store(tmp_path / "state"))


def entry(**over) -> HistoryEntry:
    base = dict(
        id="e1", kind="file", title="лекция.m4a", source_language="en",
        target_language="ru", duration=453.0, created="2026-09-17T12:00:00",
    )
    base.update(over)
    return HistoryEntry(**base)


# -- a job starts when it is asked to -----------------------------------

def test_choosing_a_file_does_not_start_the_job(window):
    """It loads models, runs for minutes and may send lines to a service.
    That is not something to begin because a file was dropped."""
    from lt_ui.screens.upload import _EXAMPLE, _Ready

    window.goto("upload")
    window._upload.open_path(_EXAMPLE)
    assert isinstance(window._upload._stack.currentWidget(), _Ready)
    assert not window._upload._pending


def test_the_chosen_file_is_named_before_starting(window):
    from lt_ui.screens.upload import _EXAMPLE

    window.goto("upload")
    window._upload.open_path(_EXAMPLE)
    assert _EXAMPLE.name in window._upload._ready._name.text()


def test_another_file_goes_back_without_starting(window):
    from lt_ui.screens.upload import _EXAMPLE, _Idle

    window.goto("upload")
    window._upload.open_path(_EXAMPLE)
    window._upload.reset()
    assert isinstance(window._upload._stack.currentWidget(), _Idle)
    assert window._upload._path is None


def test_a_missing_file_still_says_so(window, tmp_path):
    window.goto("upload")
    window._upload.open_path(tmp_path / "absent.mp4")
    assert "absent.mp4" in window._upload._busy._stage.text()


def test_the_language_pair_is_read_from_the_page_in_front(window):
    """Two pages carry a pair. Reading the wrong one threw away a change made
    on the confirmation screen without a sign."""
    from lt_ui.screens.upload import _EXAMPLE

    window.goto("upload")
    window._upload.open_path(_EXAMPLE)
    window._upload._ready.pair.set_pair("de", "ru")
    window._upload._sync_pair()
    assert window.store.settings.to_lang == "ru"
    assert window.store.settings.from_lang == "de"


# -- the history can be reached and cleared -----------------------------

def test_a_row_offers_the_folder_when_there_is_one(window, tmp_path):
    from lt_ui import glass

    folder = tmp_path / "job"
    folder.mkdir()
    window.store.add(entry(folder=str(folder)))
    window.goto("history")
    links = window._history.findChildren(glass.TextLink)
    assert any("папк" in link.text().lower() or "folder" in link.text().lower()
               or "ordner" in link.text().lower() for link in links)


def test_a_row_with_no_folder_offers_nothing_to_open(window):
    """A link that opens nothing is worse than no link."""
    from lt_ui import glass

    window.store.add(entry(folder=""))
    window.goto("history")
    labels = [link.text() for link in window._history.findChildren(glass.TextLink)]
    assert all("Очистить" in text for text in labels)


def test_the_label_matches_what_the_link_does(window, tmp_path):
    """It was called «Скачать» and it opened a folder. A label describing a
    different action is worse than none."""
    from lt_ui import glass

    folder = tmp_path / "job"
    folder.mkdir()
    window.store.add(entry(folder=str(folder)))
    window.goto("history")
    labels = [link.text() for link in window._history.findChildren(glass.TextLink)]
    assert not any("Скачать" in text for text in labels)


def test_clearing_asks_once_first(window):
    window.store.add(entry())
    window.goto("history")
    window._history._on_clear()
    assert len(window.store.entries) == 1
    assert "ещё раз" in window._history._clear.text()


def test_the_second_press_clears_the_list(window):
    window.store.add(entry())
    window.goto("history")
    window._history._on_clear()
    window._history._on_clear()
    assert window.store.entries == []


def test_clearing_the_list_leaves_the_files(window, tmp_path):
    """The entries name folders a user may still want, and a button in a list
    is not where anyone expects gigabytes to be deleted."""
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "result.wav").write_bytes(b"0" * 64)
    window.store.add(entry(folder=str(folder)))
    window.store.clear_history()
    assert (folder / "result.wav").exists()


def test_coming_back_finds_the_confirmation_disarmed(window):
    """Returning to a primed button would be a trap: one press away from
    clearing a list the user came back to look at."""
    window.store.add(entry())
    window.goto("history")
    window._history._on_clear()
    window.goto("home")
    window.goto("history")
    assert "ещё раз" not in window._history._clear.text()
    assert len(window.store.entries) == 1


def test_the_clear_action_hides_when_there_is_nothing_to_clear(window):
    window.goto("history")
    assert not window._history._header.isVisible()


# -- the subtitle formats explain themselves ----------------------------

@pytest.mark.parametrize("value,marker", [
    ("srt", "плееры"), ("vtt", "веб"), ("txt", "без времени"),
])
def test_each_format_says_what_it_is_for(window, value, marker):
    """Three acronyms and no way to choose between them is a guess."""
    i18n.set_language("ru")
    window.store.settings.sub_format = value
    window.goto("settings")
    window._settings._show_format()
    assert marker in window._settings._format_note.text()


def test_the_explanation_follows_the_choice(window):
    i18n.set_language("ru")
    window.goto("settings")
    window._settings._sync_format("txt")
    first = window._settings._format_note.text()
    window._settings._sync_format("srt")
    assert window._settings._format_note.text() != first


# -- the key field has room for its own border --------------------------

def test_the_key_row_is_taller_than_the_field_in_it(window):
    """At exactly the field's height the bottom border is clipped away."""
    from lt_ui.screens.settings import _ROW_HEIGHT

    window.goto("settings")
    field = window._settings._key
    assert window._settings._key_wrap.minimumHeight() > field.height()
    assert _ROW_HEIGHT >= 34


# -- the name, where it was asked to be ---------------------------------

def test_the_name_sits_in_the_top_left_corner(window):
    """Asked for plainly: top left, inset from both edges, level with the bar.
    It had been riding inside the centred nav pill, which put it wherever the
    centre happened to fall.
    """
    window.resize(1280, 860)
    window.show()
    window.goto("home")
    corner = window._mark.mapTo(window, window._mark.rect().topLeft())
    assert corner.x() > 0 and corner.y() > 0
    assert corner.x() == corner.y(), "отступ слева и сверху должен совпадать"


def test_the_name_is_level_with_the_nav(window):
    """Level on a shared centre line, not a shared top edge: at twice the
    size the name is taller than the bar, and matching their tops would put
    the bar visibly high beside it."""
    window.resize(1280, 860)
    window.show()
    window.goto("home")
    mark = window._mark.mapTo(window, window._mark.rect().center())
    nav = window._nav.mapTo(window, window._nav.rect().center())
    assert abs(mark.y() - nav.y()) <= 1


def test_the_nav_stays_centred_on_the_window(window):
    """The name takes room on the left, so the same room is given back on the
    right -- otherwise the bar drifts off centre by the width of a word."""
    window.resize(1280, 860)
    window.show()
    window.goto("home")
    nav = window._nav.mapTo(window, window._nav.rect().topLeft())
    centre = nav.x() + window._nav.width() / 2
    assert abs(centre - window.width() / 2) <= 2


def test_the_nav_no_longer_carries_the_name(window):
    """One surface, one job."""
    from PySide6.QtWidgets import QLabel

    labels = [w.text() for w in window._nav.findChildren(QLabel)]
    assert "Linguaflow" not in labels


def test_the_name_has_no_panel_behind_it(window):
    """It is not a control, and a surface would make it look like one."""
    from lt_ui import glass

    assert not isinstance(window._mark, glass.GlassPanel)


def test_the_name_reports_its_own_size(window):
    """A widget that paints itself must, or the layout that balances the bar
    is handed -1 and the bar sits half a word off centre."""
    assert window._mark.sizeHint().width() == window._mark.width() > 0


def test_the_gold_is_a_ramp_not_a_colour():
    """A single gold is paint. What reads as metal is the ramp: a dark base,
    a bright band where the light catches, a shadowed middle."""
    from PySide6.QtGui import QColor

    from lt_ui import theme

    ramp = theme.gold_ramp()
    assert len(ramp) >= 5
    lightness = [QColor(colour).lightness() for _stop, colour in ramp]
    assert max(lightness) - min(lightness) > 90, "плоский градиент — не металл"
    assert ramp[0][0] == 0.0 and ramp[-1][0] == 1.0


def test_the_light_theme_deepens_the_same_metal():
    """The bright band that reads as a highlight over a dark photograph
    becomes a hole over a pale one."""
    from PySide6.QtGui import QColor

    from lt_ui import theme

    theme.set_mode(theme.DARK)
    dark = [QColor(c).lightness() for _s, c in theme.gold_ramp()]
    theme.set_mode(theme.LIGHT)
    light = [QColor(c).lightness() for _s, c in theme.gold_ramp()]
    theme.set_mode(theme.DARK)
    assert max(light) < max(dark)
    assert sum(light) < sum(dark)


def test_the_drawn_name_fits_its_own_shadow(monkeypatch, tmp_path, app):
    """Of the fallback, which is what draws: the extrusion and the shadow fall
    outside the letters, so a band cut to the text clips both."""
    from PySide6.QtGui import QFontMetrics

    from lt_ui.widgets import Wordmark

    monkeypatch.setattr(Wordmark, "SOURCE", tmp_path / "absent.png")
    mark = Wordmark()
    metrics = QFontMetrics(mark._font)
    assert mark.width() > metrics.horizontalAdvance(mark._text)
    assert mark.height() > metrics.height()


def test_the_wordmark_uses_an_ornate_face_that_is_installed():
    """Asking for a font that is not there does not fail: Qt substitutes
    something else, and a customer would get a sans-serif wordmark nobody
    chose. The chain picks the first family actually present."""
    from PySide6.QtGui import QFontDatabase

    from lt_ui import theme

    chosen = theme.mark_family()
    assert chosen in QFontDatabase.families()
    assert chosen in theme.MARK_FAMILIES or chosen == theme.FAMILY


def test_the_fallback_chain_ends_somewhere_guaranteed():
    """The last entries ship with Windows, so the chain cannot run out."""
    from lt_ui import theme

    assert "Segoe Script" in theme.MARK_FAMILIES
    assert theme.MARK_FAMILIES[0] == "Script MT Bold"


def test_the_wordmark_is_not_set_in_the_interface_face(window):
    """The drawn fallback is the product's name, not a label."""
    from lt_ui import theme

    assert window._mark._font.family() != theme.FAMILY


def test_the_supplied_logotype_is_used(window):
    """It was drawn by hand here until the designer's own file arrived. The
    made thing wins over the approximation of it."""
    from lt_ui.widgets import Wordmark

    assert Wordmark.SOURCE.exists(), "логотип должен лежать в assets"
    assert window._mark.uses_logo


def test_the_logotype_is_trimmed_to_its_letters():
    """Its height on screen must be the height of the lettering, not of the
    canvas it was exported on."""
    import numpy as np
    from PySide6.QtGui import QImage

    from lt_ui.widgets import Wordmark

    image = QImage(str(Wordmark.SOURCE)).convertToFormat(QImage.Format_ARGB32)
    height, width = image.height(), image.width()
    raw = np.frombuffer(image.constBits(), dtype=np.uint8)
    alpha = raw.reshape(height, image.bytesPerLine() // 4, 4)[:, :width, 3]
    assert alpha[0].max() > 12 or alpha[-1].max() > 12, "сверху или снизу пусто"
    assert alpha[:, 0].max() > 12 or alpha[:, -1].max() > 12, "по бокам пусто"


def test_a_missing_logotype_leaves_a_wordmark_not_a_gap(window, monkeypatch, tmp_path):
    """A file that is absent or unreadable must not cost the name."""
    from lt_ui.widgets import Wordmark

    monkeypatch.setattr(Wordmark, "SOURCE", tmp_path / "absent.png")
    mark = Wordmark()
    assert not mark.uses_logo
    assert mark.width() > 0 and mark.height() > 0


# -- the busy screen is not a dead end ----------------------------------

def test_a_failure_offers_the_way_back(window):
    """It used to write the message and leave the user there: no button, and
    leaving through the nav came back to the same page."""
    window.goto("upload")
    busy = window._upload._busy
    window._upload._stack.setCurrentWidget(busy)
    window._upload._on_fail("Сервис отклонил ключ доступа.")
    assert busy._ok.isVisible() or not busy.isVisible()
    assert "ключ" in busy._stage.text()


def test_the_way_back_leads_to_a_new_upload(window):
    from lt_ui.screens.upload import _Idle

    window.goto("upload")
    window._upload._stack.setCurrentWidget(window._upload._busy)
    window._upload._on_fail("что-то пошло не так")
    window._upload._busy._ok.click()
    assert isinstance(window._upload._stack.currentWidget(), _Idle)
    assert window._upload._path is None


def test_the_button_is_absent_while_the_job_runs(window):
    """There is nothing to acknowledge yet, and it is not a cancel."""
    window.goto("upload")
    window._upload._busy.reset("clip.mp4")
    assert window._upload._busy._ok.isHidden()


def test_the_ring_stops_short_while_work_continues(window):
    """It measures recognition, which finishes well before the job does.
    A full ring over «assembling the video» reads as finished and frozen."""
    busy = window._upload._busy
    busy.set_progress(1.0)
    assert busy._ring._value < 1.0
    assert busy._ring._value >= 0.98


def test_the_progress_ring_keeps_moving_while_running(window):
    """A parked 80% used to look frozen. The comet on the rim is the pulse."""
    ring = window._upload._busy._ring
    ring.set_running(True)
    assert ring.is_running
    before = ring._phase
    ring._advance()
    assert ring._phase != before
    ring.set_running(False)
    assert not ring.is_running


def test_elapsed_time_ticks_on_the_busy_screen(window):
    import time

    busy = window._upload._busy
    busy.reset("clip.mp4")
    busy._origin = time.monotonic() - 94
    busy._refresh_clock()
    assert "01:34" in busy._elapsed.text()


def test_after_recognition_the_busy_screen_says_work_continues(window):
    """80% is the end of recognition, not of the job. Say so, or the wait
    looks like a hang."""
    busy = window._upload._busy
    busy.reset("clip.mp4")
    assert busy._hint.isHidden()
    busy.set_progress(0.80)
    assert not busy._hint.isHidden()
    assert "перевод" in busy._hint.text()


def test_a_failure_stops_the_busy_motion(window):
    busy = window._upload._busy
    busy.reset("clip.mp4")
    busy._ring.set_running(True)
    window._upload._on_fail("нет звука")
    assert not busy._ring.is_running
    assert busy._hint.isHidden()


def test_starting_again_hides_the_button(window):
    window.goto("upload")
    window._upload._stack.setCurrentWidget(window._upload._busy)
    window._upload._on_fail("ошибка")
    window._upload._busy.reset("clip.mp4")
    assert window._upload._busy._ok.isHidden()


# -- a language the recording contradicts -------------------------------

def _finished(detected: str, probability: float):
    """A finished job, of the shape the result screen is handed."""
    from types import SimpleNamespace

    from lt_core.asr.types import Transcript
    from lt_core.subtitles.cues import Cue

    transcript = Transcript(
        segments=(), language="en", language_probability=1.0, duration=12.0,
        detected_language=detected, detected_probability=probability,
    )
    return SimpleNamespace(
        transcript=transcript,
        media=SimpleNamespace(title="лекция.m4a", duration=12.0),
        cues=(Cue(index=1, start=0.0, end=2.0, lines=("Hello there.",)),),
        translated_cues=(Cue(index=1, start=0.0, end=2.0, lines=("Здравствуйте.",)),),
        outputs={},
    )


def _texts(widget) -> str:
    """Every label on the widget, folded -- the eyebrow style uppercases."""
    from PySide6.QtWidgets import QLabel

    return " ".join(
        child.text() for child in widget.findChildren(QLabel)).casefold()


def test_a_recording_in_another_language_says_so_on_the_result(window):
    """Told that Russian speech is English, Whisper writes fluent English that
    reads exactly like a good transcript. The result screen is the last place
    it can be caught before the reader believes it."""
    from types import SimpleNamespace

    window.goto("upload")
    done = window._upload._done
    settings = SimpleNamespace(detect_language=False, to_lang="ru")
    done.show_result(_finished("ru", 1.0), settings)
    shown = _texts(done)
    assert i18n._("Проверьте язык").casefold() in shown
    assert "звуковую дорожку" in shown, (
        "the reason, not just the heading"
    )
    assert "русский" in shown, "the language actually heard"


def test_a_recording_that_agrees_says_nothing(window):
    from types import SimpleNamespace

    window.goto("upload")
    done = window._upload._done
    settings = SimpleNamespace(detect_language=False, to_lang="ru")
    done.show_result(_finished("en", 1.0), settings)
    assert i18n._("Проверьте язык").casefold() not in _texts(done)


# -- nothing clickable stays silent -------------------------------------

def test_no_clickable_surface_on_any_screen_ignores_the_pointer(window):
    """The complaint that started this was one card on one screen. This is
    the same question asked of every control the app actually builds, which
    is the only way the answer stays true as screens are added.

    The pointer is delivered as a real enter and leave, so a control is
    judged by what it draws rather than by which base class it inherits.
    """
    from PySide6.QtCore import QEvent, QPropertyAnimation, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import (
        QAbstractButton, QApplication, QComboBox, QLineEdit, QWidget,
    )

    def painted(widget) -> bytes:
        image = QImage(widget.size(), QImage.Format_ARGB32)
        image.fill(0)
        widget.render(image)
        return image.constBits().tobytes()

    def settle(widgets) -> None:
        """Run any animation the pointer just started to its end.

        A control that answers by animating has not answered yet on the
        frame the event arrives, and a test that looks then would call it
        silent.
        """
        QApplication.processEvents()
        for widget in widgets:
            for animation in widget.findChildren(QPropertyAnimation):
                if animation.state() == QPropertyAnimation.Running:
                    animation.setCurrentTime(animation.duration())
        QApplication.processEvents()

    def answers(widget) -> bool:
        """Something visible changes when the pointer arrives.

        Not necessarily on the widget itself: the navigation bar draws one
        pane of glass that runs between its five destinations, so a
        destination is answered by its parent rather than by its own pixels.
        """
        watched = [widget]
        if widget.parentWidget() is not None:
            watched.append(widget.parentWidget())
        QApplication.sendEvent(widget, QEvent(QEvent.Leave))
        settle(watched)
        resting = [painted(w) for w in watched]
        QApplication.sendEvent(widget, QEvent(QEvent.Enter))
        settle(watched)
        hovered = [painted(w) for w in watched]
        QApplication.sendEvent(widget, QEvent(QEvent.Leave))
        settle(watched)
        return bool(resting[0]) and any(
            before != after for before, after in zip(resting, hovered)
        )

    window.resize(1280, 860)
    window.show()
    silent: list[str] = []
    checked = 0
    try:
        for screen in ("home", "upload", "realtime", "settings", "history"):
            window.goto(screen)
            QApplication.processEvents()
            for widget in window.findChildren(QWidget):
                if isinstance(widget, (QComboBox, QLineEdit)):
                    # Drawn by Qt's style sheets rather than the shared
                    # painter; theirs is checked as CSS in test_appearance.
                    continue
                if widget.testAttribute(Qt.WA_TransparentForMouseEvents):
                    # A label inside a card inherits the card's hand cursor
                    # and cannot receive the mouse; the card answers for it.
                    continue
                clickable = (
                    isinstance(widget, QAbstractButton)
                    or widget.cursor().shape() == Qt.PointingHandCursor
                )
                if not clickable or not widget.isVisible():
                    continue
                checked += 1
                if not answers(widget):
                    label = getattr(widget, "text", lambda: "")() or ""
                    silent.append(f"{screen}: {type(widget).__name__} {label!r}")
    finally:
        window.hide()

    assert checked > 30, (
        f"only {checked} controls were reached; a sweep that finds nothing "
        f"to look at passes for the wrong reason"
    )
    assert silent == [], silent


# -- one capsule, travelling ---------------------------------------------

def _nav(window):
    from lt_ui.widgets import NavBar, NavItem

    bar = window.findChild(NavBar)
    return bar, {item.key: item for item in bar.findChildren(NavItem)}


# -- no lit band along the top of anything -------------------------------

def _top_rows(widget, count: int = 6):
    """Mean lightness of each of the first rows of a widget's own pixels."""
    from PySide6.QtGui import QColor, QImage

    image = QImage(widget.size(), QImage.Format_ARGB32)
    image.fill(0)
    widget.render(image)
    rows = []
    for y in range(count):
        # The rounded corners are transparent, so only the middle is read.
        sample = range(image.width() // 3, 2 * image.width() // 3)
        rows.append(sum(QColor(image.pixelColor(x, y)).lightness()
                        for x in sample) / len(list(sample)))
    return rows


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_no_glass_surface_wears_a_lit_band_along_its_top(window, mode):
    """Reported from use: the bright two-pixel edge along the top of the
    navigation, the mode chips and the switch pill. It was the recipe's inset
    highlight, drawn on every glass surface -- and absent from the picker and
    the text field, which are styled by Qt rather than painted, which is why
    those two looked right and everything else did not.
    """
    from PySide6.QtWidgets import QApplication

    from lt_ui.widgets import NavBar

    window.store.settings.appearance = mode
    window.apply_appearance()
    window.resize(1280, 860)
    window.show()
    try:
        window.goto("realtime")
        QApplication.processEvents()
        bar = window.findChild(NavBar)
        rows = _top_rows(bar)
        # Row nought is the hairline edge, which runs all the way round the
        # shape and is meant to be there. The band sat beneath it.
        body = max(rows[3:])
        assert rows[1] <= body + 4 and rows[2] <= body + 4, (
            f"a band is lit beneath the top edge: {rows}"
        )
    finally:
        window.hide()


# -- the runner belongs to the pointer, the page to its word --------------

def _nav(window):
    from lt_ui.widgets import NavBar, NavItem

    bar = window.findChild(NavBar)
    return bar, {item.key: item for item in bar.findChildren(NavItem)}


def _painted_alone(widget) -> bytes:
    from PySide6.QtGui import QImage

    image = QImage(widget.size(), QImage.Format_ARGB32)
    image.fill(0)
    widget.render(image)
    return image.constBits().tobytes()


def _finish(animation):
    from PySide6.QtCore import QPropertyAnimation

    if animation.state() == QPropertyAnimation.Running:
        animation.setCurrentTime(animation.duration())


def test_nothing_runs_in_the_bar_until_the_pointer_is_in_it(window):
    """Asked for: the open page says so through its own word, and the pane of
    glass appears only under the pointer."""
    from PySide6.QtWidgets import QApplication

    window.resize(1280, 860)
    window.show()
    try:
        window.goto("realtime")
        QApplication.processEvents()
        bar, _items = _nav(window)
        _finish(bar._fade)
        assert bar.shown == 0.0
    finally:
        window.hide()


def test_the_open_page_is_told_apart_by_its_word_alone(window):
    """Which is what the runner is freed up to stop saying."""
    from PySide6.QtWidgets import QApplication

    window.resize(1280, 860)
    window.show()
    try:
        window.goto("realtime")
        QApplication.processEvents()
        _bar, items = _nav(window)
        open_item, other = items["realtime"], items["history"]
        assert open_item.isChecked() and not other.isChecked()
        assert open_item.OPEN_WEIGHT > open_item.RESTING_WEIGHT
        assert _painted_alone(open_item) != _painted_alone(other), (
            "the two words are drawn identically"
        )
    finally:
        window.hide()


def test_the_runner_appears_where_the_pointer_is_and_then_travels(window):
    from PySide6.QtCore import QEvent, QRectF
    from PySide6.QtWidgets import QApplication

    window.resize(1280, 860)
    window.show()
    try:
        window.goto("realtime")
        QApplication.processEvents()
        bar, items = _nav(window)
        _finish(bar._fade)

        QApplication.sendEvent(items["upload"], QEvent(QEvent.Enter))
        assert bar.runner == QRectF(items["upload"].geometry()), (
            "it slid in from somewhere instead of appearing under the pointer"
        )
        _finish(bar._fade)
        assert bar.shown == 1.0

        QApplication.sendEvent(items["upload"], QEvent(QEvent.Leave))
        QApplication.sendEvent(items["settings"], QEvent(QEvent.Enter))
        QApplication.processEvents()
        assert bar._glide.endValue() == QRectF(items["settings"].geometry()), (
            "it jumped between destinations instead of travelling"
        )
        _finish(bar._glide)
        assert bar.runner == QRectF(items["settings"].geometry())
        assert bar.shown == 1.0, "it should not blink on the way across"

        QApplication.sendEvent(items["settings"], QEvent(QEvent.Leave))
        QApplication.processEvents()
        _finish(bar._fade)
        assert bar.shown == 0.0, "it stayed behind after the pointer left"
    finally:
        window.hide()


def test_leaving_one_destination_for_the_next_does_not_put_it_out(window):
    """Qt can deliver the arrival before the departure. Taken literally that
    fades the runner out just as it should be setting off."""
    from PySide6.QtCore import QEvent, QRectF
    from PySide6.QtWidgets import QApplication

    window.resize(1280, 860)
    window.show()
    try:
        window.goto("home")
        QApplication.processEvents()
        bar, items = _nav(window)

        QApplication.sendEvent(items["upload"], QEvent(QEvent.Enter))
        QApplication.sendEvent(items["history"], QEvent(QEvent.Enter))
        QApplication.sendEvent(items["upload"], QEvent(QEvent.Leave))
        QApplication.processEvents()
        _finish(bar._glide)
        _finish(bar._fade)
        assert bar.shown == 1.0
        assert bar.runner == QRectF(items["history"].geometry())
    finally:
        window.hide()


# -- how much of the window there is ------------------------------------

def test_the_window_itself_is_translucent(window):
    """Everything the window draws goes through this, text included, so it is
    the one appearance setting that can cost legibility rather than only
    looks.

    Not `setWindowOpacity`, which was the first attempt: it makes the whole
    window a layered one blended against the literal desktop, so the frosted
    sheet the compositor composes behind it is never seen. Measured at 0.5
    with the backdrop asked for and granted -- a page of text behind the
    window was readable through it, word for word.
    """
    from PySide6.QtCore import Qt

    from lt_ui import theme

    assert 0.0 < theme.WINDOW_OPACITY < 1.0
    assert window.testAttribute(Qt.WA_TranslucentBackground), (
        "the surface has to carry alpha for anything to come through it"
    )


def test_the_window_asks_for_the_desktop_behind_it_to_be_blurred(window):
    """Without it the desktop shows through exactly as it is -- text, icons,
    other windows -- competing with the interface over it."""
    import inspect

    from lt_ui import system_backdrop

    assert hasattr(window, "blurred_behind")
    source = inspect.getsource(system_backdrop.blur_behind)
    assert "SetWindowCompositionAttribute" in source


@pytest.mark.parametrize("mode, fill", [("dark", "TINT_DARK"), ("light", "TINT_LIGHT")])
def test_the_styled_controls_keep_step_with_the_painted_ones(mode, fill):
    """The picker and the text field are the only two surfaces drawn by Qt's
    style sheets rather than by the shared recipe, and twice now they have
    drifted from it in ways a user had to report: once carrying a hover rule
    nothing else had, once missing the top band everything else wore. Their
    fill is written as a number in CSS, so nothing but this keeps it in step.
    """
    import re

    from lt_ui import glass, theme

    wanted = getattr(theme, fill)
    for widget in (glass.GlassSelect, glass.GlassInput):
        sheet = getattr(widget, mode.upper())
        found = re.search(r"background: rgba\(255,255,255,([\d.]+)\);", sheet)
        assert found, widget.__name__
        assert abs(float(found.group(1)) - wanted) <= 0.12, (
            f"{widget.__name__} in {mode}: {found.group(1)} against {wanted}"
        )


# -- a switch that is on looks like a switch that is on ------------------

def _switch_image(toggle):
    from PySide6.QtGui import QImage

    image = QImage(toggle.size(), QImage.Format_ARGB32)
    image.fill(0)
    toggle.render(image)
    return image.constBits().tobytes()


def test_a_switch_restored_from_settings_points_the_right_way(app):
    """Reported from use: after a restart every switch that was on was lit in
    the accent colour and had its knob over on the left, where off lives.

    The knob moved on `toggled`, and everything that restores a saved setting
    blocks that signal first -- otherwise setting the switch writes the
    setting straight back. So the fill knew and the knob did not.
    """
    from lt_ui import glass

    restored = glass.Toggle()
    restored.blockSignals(True)
    restored.setChecked(True)
    restored.blockSignals(False)

    born_on = glass.Toggle(on=True)
    assert _switch_image(restored) == _switch_image(born_on), (
        "a switch turned on quietly does not look like one that was born on"
    )


def test_a_switch_turned_off_quietly_points_the_other_way(app):
    from lt_ui import glass

    restored = glass.Toggle(on=True)
    restored.blockSignals(True)
    restored.setChecked(False)
    restored.blockSignals(False)

    assert _switch_image(restored) == _switch_image(glass.Toggle())


def test_the_settings_screen_shows_every_saved_switch_the_right_way(window):
    """The whole point of the above, on the screen it was reported on."""
    from PySide6.QtWidgets import QApplication

    from lt_ui import glass

    window.store.settings.voiceover = True
    window.store.settings.match_voices = True
    window.store.settings.notify = True
    window.goto("settings")
    window._settings.refresh()
    QApplication.processEvents()

    wrong = [
        toggle for toggle in window._settings.findChildren(glass.Toggle)
        if toggle.isChecked() and toggle._position != glass.Toggle.ON
    ]
    assert wrong == [], f"{len(wrong)} switches are lit and pointing left"
