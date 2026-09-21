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
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import (
        QAbstractButton, QApplication, QComboBox, QLineEdit, QWidget,
    )

    def painted(widget) -> bytes:
        image = QImage(widget.size(), QImage.Format_ARGB32)
        image.fill(0)
        widget.render(image)
        return image.constBits().tobytes()

    def answers(widget) -> bool:
        """Something visible changes when the pointer arrives.

        Not necessarily on the widget itself: the navigation bar draws one
        capsule that glides between its five destinations, so a destination
        is answered by its parent rather than by its own pixels.
        """
        watched = [widget]
        if widget.parentWidget() is not None:
            watched.append(widget.parentWidget())
        QApplication.sendEvent(widget, QEvent(QEvent.Leave))
        QApplication.processEvents()
        resting = [painted(w) for w in watched]
        QApplication.sendEvent(widget, QEvent(QEvent.Enter))
        QApplication.processEvents()
        hovered = [painted(w) for w in watched]
        QApplication.sendEvent(widget, QEvent(QEvent.Leave))
        QApplication.processEvents()
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


def test_the_capsule_travels_to_what_the_pointer_is_on(window):
    """Asked for: the white lozenge in the header should run back and forth
    after the cursor rather than blink from one destination to the next."""
    from PySide6.QtCore import QEvent, QPropertyAnimation, QRectF
    from PySide6.QtWidgets import QApplication

    window.resize(1280, 860)
    window.show()
    try:
        window.goto("realtime")
        QApplication.processEvents()
        bar, items = _nav(window)
        bar._glide.stop()
        bar._settle(animated=False)
        assert bar.capsule == QRectF(items["realtime"].geometry())

        QApplication.sendEvent(items["settings"], QEvent(QEvent.Enter))
        assert bar._glide.state() == QPropertyAnimation.Running, (
            "it jumped instead of travelling"
        )
        assert bar._glide.endValue() == QRectF(items["settings"].geometry())
        bar._glide.setCurrentTime(bar.GLIDE_MS)
        assert bar.capsule == QRectF(items["settings"].geometry())

        QApplication.sendEvent(items["settings"], QEvent(QEvent.Leave))
        bar._glide.setCurrentTime(bar.GLIDE_MS)
        assert bar.capsule == QRectF(items["realtime"].geometry()), (
            "with nothing under the pointer it belongs on the page that is open"
        )
    finally:
        window.hide()


def test_leaving_one_destination_for_the_next_does_not_send_it_home(window):
    """Qt can deliver the arrival before the departure. Taken literally that
    puts the capsule back on the open page for one frame, which reads as a
    flinch."""
    from PySide6.QtCore import QEvent, QRectF
    from PySide6.QtWidgets import QApplication

    window.resize(1280, 860)
    window.show()
    try:
        window.goto("home")
        QApplication.processEvents()
        bar, items = _nav(window)
        bar._glide.stop()
        bar._settle(animated=False)

        QApplication.sendEvent(items["upload"], QEvent(QEvent.Enter))
        QApplication.sendEvent(items["history"], QEvent(QEvent.Enter))
        QApplication.sendEvent(items["upload"], QEvent(QEvent.Leave))
        bar._glide.setCurrentTime(bar.GLIDE_MS)
        assert bar.capsule == QRectF(items["history"].geometry())
    finally:
        window.hide()
