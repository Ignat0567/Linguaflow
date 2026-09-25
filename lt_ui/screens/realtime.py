"""Live translation: one microphone, subtitles as the speaker talks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from lt_core.subtitles.export import to_srt, write
from lt_core.realtime.session import append_committed
from lt_core.subtitles.cues import Cue

from .. import glass, theme
from ..i18n import _
from ..store import HistoryEntry, format_clock, new_id
from ..widgets import ChipGroup, LanguagePair, clear_fill


@dataclass
class Line:
    original: str = ""
    translated: str = ""
    speaker: str | None = None
    partial: str = ""
    #: The sentence still being spoken, translated provisionally. Shown in the
    #: same lighter hand as `partial`, and replaced by `translated` when the
    #: sentence finishes.
    partial_translated: str = ""


class RealtimeScreen(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        clear_fill(self)
        self._lines: list[Line] = []
        self._current = Line()
        self._pending_start = False
        #: True while the engine's live session is this screen's. The
        #: browser screen runs its own sessions on the same engine.
        self._mine = False
        self._ever = False
        self._saved: Path | None = None

        self._pair = LanguagePair(self, compact=True)
        self._pair.changed.connect(self._sync_pair)
        self._modes = ChipGroup((
            ("subtitles", _("Субтитры")),
            ("conversation", _("Разговор")),
        ), self, stretch=False)
        self._modes.changed.connect(self._sync_mode)
        mode_pill = glass.GlassPanel(self, radius=theme.RADIUS_PILL)
        mode_pill.setFixedHeight(42)
        mode_row = QHBoxLayout(mode_pill)
        mode_row.setContentsMargins(8, 4, 8, 4)
        mode_row.setSpacing(0)
        mode_row.addWidget(self._modes)

        # Where the sound comes from sits beside what is done with it: a
        # talk in the room and a call on the speakers are the same session
        # with a different ear, and it was two screens away in Settings.
        self._capture = ChipGroup((
            ("microphone", _("Микрофон")),
            ("system", _("Звук системы")),
        ), self, stretch=False)
        self._capture.changed.connect(self._sync_capture)
        capture_pill = glass.GlassPanel(self, radius=theme.RADIUS_PILL)
        capture_pill.setFixedHeight(42)
        capture_row = QHBoxLayout(capture_pill)
        capture_row.setContentsMargins(8, 4, 8, 4)
        capture_row.setSpacing(0)
        capture_row.addWidget(self._capture)

        # Reading the translation out loud is an option, not a third kind of
        # session. It used to be one, which meant a conversation -- where
        # hearing it matters most -- was the one place it could not be had.
        self._speak = glass.Toggle(self)
        self._speak.toggled.connect(self._sync_voice)
        speak_pill = glass.GlassPanel(self, radius=theme.RADIUS_PILL)
        speak_pill.setFixedHeight(42)
        speak_row = QHBoxLayout(speak_pill)
        speak_row.setContentsMargins(16, 4, 10, 4)
        speak_row.setSpacing(12)
        speak_row.addWidget(glass.label(_("Озвучивать"), 13, 500, 0.82))
        speak_row.addWidget(self._speak)

        controls = QHBoxLayout()
        controls.setSpacing(16)
        controls.addStretch()
        controls.addWidget(self._pair)
        controls.addWidget(mode_pill)
        controls.addWidget(capture_pill)
        controls.addWidget(speak_pill)
        controls.addStretch()

        self._record = glass.RecordButton(self)
        self._record.toggled.connect(self._toggled)
        self._status = glass.label(
            _("Нажмите, чтобы начать запись"), 13, 400, 0.70, wrap=True
        )
        self._status.setAlignment(Qt.AlignCenter)
        # A refusal is a paragraph, not a word. On one line it pushed the whole
        # screen wider than the window -- the row of switches slid off the
        # right edge and the message itself was cut off at both ends. Wrapped,
        # it was then squeezed to a line and a half by the panel under it; it
        # keeps the height its text needs.
        self._status.setFixedWidth(720)
        self._status.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)

        self._panel = glass.GlassPanel(self, radius=theme.RADIUS_PANEL)
        self._panel.setMinimumHeight(200)
        self._panel.setMaximumWidth(760)
        # The lines scroll inside the panel. They used to be laid straight
        # into it, the last eight of them: on a meeting with long sentences
        # eight lines were taller than the window, and the panel grew up
        # over the controls and the record button.
        self._scroll = _FeedScroll(self._panel)
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(8, 12, 8, 12)
        panel_layout.addWidget(self._scroll)
        self._feed = self._scroll.feed
        self._placeholder = glass.label(
            _("Субтитры появятся здесь"), 13, 400, theme.MUTED
        )
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._feed.addWidget(self._placeholder)

        self._save = glass.GlassButton(_("Сохранить транскрипт"), self)
        self._save.clicked.connect(self._save_transcript)
        self._save.hide()
        self._overlay_btn = glass.GlassButton(_("Окно субтитров"), self)
        self._overlay_btn.clicked.connect(self._toggle_overlay)

        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self._overlay_btn)
        actions.addWidget(self._save)
        actions.addStretch()

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(18)
        root.addLayout(controls)
        rec = QHBoxLayout()
        rec.addStretch()
        rec.addWidget(self._record)
        rec.addStretch()
        root.addSpacing(8)
        root.addLayout(rec)
        # Centred by stretches, not by an alignment flag: a layout item with
        # an alignment is not asked for its height at a given width, and the
        # wrapped text was cut to the height of a line and a half.
        status_row = QHBoxLayout()
        status_row.addStretch()
        status_row.addWidget(self._status)
        status_row.addStretch()
        root.addLayout(status_row)
        panel_row = QHBoxLayout()
        panel_row.addStretch()
        panel_row.addWidget(self._panel, 1)
        panel_row.addStretch()
        root.addLayout(panel_row, 1)
        root.addLayout(actions)

        engine = app.engine
        engine.status.connect(self._status.setText)
        engine.ready.connect(self._on_ready)
        engine.failed.connect(self._on_fail)
        engine.live_update.connect(self._on_update)
        engine.live_failed.connect(self._on_fail)
        engine.live_stopped.connect(self._on_stopped)

    def refresh(self) -> None:
        settings = self.app.store.settings
        self._pair.set_pair(settings.from_lang, settings.to_lang)
        self._modes.set_value(settings.realtime_mode)
        self._capture.set_value(settings.capture_kind)
        self._speak.blockSignals(True)
        self._speak.setChecked(settings.realtime_voice)
        self._speak.blockSignals(False)

    def hideEvent(self, event) -> None:  # noqa: N802
        if self._record.isChecked():
            self._record.setChecked(False)
        super().hideEvent(event)

    def _sync_pair(self) -> None:
        source, target = self._pair.pair()
        self.app.store.settings.from_lang = source
        self.app.store.settings.to_lang = target
        self.app.store.save_settings()

    def _sync_mode(self, mode: str) -> None:
        self.app.store.settings.realtime_mode = mode
        self.app.store.save_settings()
        self._render()

    def _sync_capture(self, kind: str) -> None:
        self.app.store.settings.capture_kind = kind
        self.app.store.save_settings()

    def _sync_voice(self, on: bool) -> None:
        self.app.store.settings.realtime_voice = on
        self.app.store.save_settings()

    def _toggled(self, on: bool) -> None:
        if on:
            if self.app.engine.live_running and not self._mine:
                self._refuse(_("Сейчас переводится видео на экране «Браузер»."))
                return
            self._pending_start = True
            self._lines.clear()
            self._current = Line()
            self._saved = None
            self._save.hide()
            self._render()
            self._status.setText(_("Загружаю модели…"))
            self.app.engine.prepare(self.app.store.settings)
        else:
            self._pending_start = False
            self.app.engine.stop_live()
            if self.app.engine.live_running:
                self._status.setText(_("Останавливаю…"))

    def _on_ready(self) -> None:
        if not self._pending_start:
            return
        self._pending_start = False
        self._mine = True
        self._status.setText(_("Слушаю…"))
        if self.app.store.settings.overlay:
            self.app.overlay.reveal()
            self.app.overlay.set_caption(listening=True)
        self.app.engine.start_live(self.app.store.settings)

    def _on_fail(self, message: str) -> None:
        if not (self._mine or self._pending_start):
            return
        self._mine = False
        self._pending_start = False
        self._refuse(message)

    def _refuse(self, message: str) -> None:
        self._status.setText(message)
        self._record.blockSignals(True)
        self._record.setChecked(False)
        self._record.blockSignals(False)

    def _on_stopped(self) -> None:
        if not self._mine:
            return
        self._mine = False
        self._ever = True
        self._record.blockSignals(True)
        self._record.setChecked(False)
        self._record.blockSignals(False)
        self._status.setText(_("Остановлено"))
        if self._lines or self._current.original:
            self._save.show()
        self._push_overlay()

    def _on_update(self, update) -> None:
        if not self._mine:
            return
        current = self._current
        if update.speaker and current.speaker and update.speaker != current.speaker:
            if current.original or current.translated:
                self._lines.append(current)
            self._current = Line(speaker=update.speaker)
            current = self._current
        if not current.speaker:
            current.speaker = update.speaker
        if update.committed:
            current.original = append_committed(current.original, update)
            current.partial = ""
        if update.partial:
            current.partial = update.partial
        current.partial_translated = update.partial_translation
        if update.translation:
            translated = (
                f"{current.translated} {update.translation}".strip()
                if current.translated else update.translation
            )
            rest = _after(current.original, update.translation_source)
            if rest is not None:
                # The line is exactly the sentences translated; whatever of
                # the next one was already heard starts the next line.
                if update.translation_source:
                    self._lines.append(Line(
                        original=update.translation_source, translated=translated,
                        speaker=current.speaker,
                    ))
                self._current = Line(speaker=update.speaker, original=rest,
                                     partial=current.partial)
            else:
                current.translated = translated
                current.partial_translated = ""
                if current.original:
                    self._lines.append(current)
                    self._current = Line(speaker=update.speaker)
        self._render()
        self._push_overlay()

    def _render(self) -> None:
        while self._feed.count():
            item = self._feed.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        visible = list(self._lines)
        if (self._current.original or self._current.partial
                or self._current.partial_translated):
            visible.append(self._current)
        if not visible:
            placeholder = glass.label(
                _("Субтитры появятся здесь"), 13, 400, theme.MUTED
            )
            placeholder.setAlignment(Qt.AlignCenter)
            self._feed.addStretch(1)
            self._feed.addWidget(placeholder)
            self._feed.addStretch(1)
            return
        conversation = self.app.store.settings.realtime_mode == "conversation"
        # Newest at the bottom, under a stretch, as a chat reads.
        self._feed.addStretch(1)
        for line in visible[-KEPT_ON_SCREEN:]:
            self._feed.addWidget(_Caption(line, conversation))
        self._scroll.refit()

    def _toggle_overlay(self) -> None:
        overlay = self.app.overlay
        visible = not overlay.isVisible()
        self.app.store.settings.overlay = visible
        self.app.store.save_settings()
        if visible:
            overlay.reveal()
            self._push_overlay()
        else:
            overlay.hide()

    def _push_overlay(self) -> None:
        overlay = getattr(self.app, "overlay", None)
        if overlay is None or not overlay.isVisible():
            return
        line = self._current
        if not (line.original or line.partial or line.translated) and self._lines:
            line = self._lines[-1]
        overlay.set_caption(
            original=(line.original + " " + line.partial).strip(),
            translated=(line.translated + " " + line.partial_translated).strip(),
            speaker=line.speaker,
            listening=self._record.isChecked(),
        )

    def _save_transcript(self) -> None:
        lines = list(self._lines)
        if self._current.original:
            lines.append(self._current)
        if not lines:
            return
        entry_id = new_id()
        folder = self.app.store.job_dir(entry_id)
        saved_at = datetime.now()
        # Named for the moment, not «live»: every session is saved into the
        # same folder, so the second one used to overwrite the first, and both
        # history entries then opened the second session's words.
        stem = base = f"live_{saved_at:%Y-%m-%d_%H-%M-%S}"
        number = 1
        while (folder / f"{stem}.srt").exists() or (folder / f"{stem}.txt").exists():
            number += 1
            stem = f"{base}_{number}"
        cues = []
        cursor = 0.0
        for index, line in enumerate(lines, start=1):
            text = line.translated or line.original
            duration = max(1.2, min(6.0, 0.06 * max(1, len(text))))
            cues.append(Cue(index, cursor, cursor + duration, (text,)))
            cursor += duration
        srt_path = write(folder / f"{stem}.srt", to_srt(tuple(cues)))
        body = "\n\n".join(
            (f"[{line.speaker}]\n" if line.speaker else "")
            + line.original
            + (f"\n{line.translated}" if line.translated else "")
            for line in lines
        )
        txt_path = write(folder / f"{stem}.txt", body + "\n")
        settings = self.app.store.settings
        worker = self.app.engine.last_live
        duration = worker.audio_seconds if worker else cursor
        self.app.store.add(HistoryEntry(
            id=entry_id, kind="live",
            title=_("Живой перевод"),
            source_language=settings.from_lang,
            target_language=settings.to_lang,
            duration=duration,
            created=saved_at.isoformat(timespec="seconds"),
            folder=str(folder),
            outputs={"srt": str(srt_path), "txt": str(txt_path)},
        ))
        self.app.history_changed()
        self._saved = folder
        self._status.setText(
            _("Сохранено · {duration}", duration=format_clock(duration))
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def _after(text: str, source: str) -> str | None:
    """`text` with the translated `source` taken off its front, or None
    when `source` is unknown or is not how `text` begins.

    Compared word by word, because the two were joined from the same words
    by different hands and may differ in spacing.
    """
    if not source:
        return None
    words, prefix = text.split(), source.split()
    if words[: len(prefix)] != prefix:
        return None
    return " ".join(words[len(prefix):])


#: Lines kept in the panel to scroll back through. Every update rebuilds
#: them, so not the whole meeting: the transcript is saved in full anyway.
KEPT_ON_SCREEN = 80


class _FeedScroll(QScrollArea):
    """The panel's lines, following the newest unless scrolled up.

    Scrolled to the bottom, it stays there as lines arrive. Scrolled up to
    read something again, it stays where it was put until taken back down.
    """

    #: How near the bottom still counts as "at the bottom", in pixels.
    NEAR = 24

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        viewport = self.viewport()
        viewport.setAutoFillBackground(False)
        viewport.setAttribute(Qt.WA_TranslucentBackground, True)
        body = QWidget()
        clear_fill(body)
        self.feed = QVBoxLayout(body)
        self.feed.setContentsMargins(24, 16, 24, 16)
        self.feed.setSpacing(18)
        self.setWidget(body)
        handle = (
            "rgba(13,15,26,0.22)" if theme.is_light() else "rgba(255,255,255,0.22)"
        )
        self.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 4px; }"
            f"QScrollBar::handle:vertical {{ background: {handle};"
            " border-radius: 4px; min-height: 32px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self.following = True
        bar = self.verticalScrollBar()
        bar.valueChanged.connect(self._moved)
        bar.rangeChanged.connect(self._grew)

    def _moved(self, value: int) -> None:
        bar = self.verticalScrollBar()
        self.following = value >= bar.maximum() - self.NEAR

    def refit(self) -> None:
        """Size the lines for the width they actually have.

        A scroll area sizes its widget by the height the layout wants at its
        *preferred* width. Wrapped lines narrower than that need more
        height than they were given: in a German meeting the third line of a
        long sentence was drawn half under its own translation.
        """
        body = self.widget()
        width = self.viewport().width()
        if body is None or width <= 0:
            return
        margins = self.feed.contentsMargins()
        room = width - margins.left() - margins.right()
        # Measured, not left to the layout: Qt's height-for-width through a
        # scroll area and a box layout gave every caption the same share,
        # 119-129 px, to lines that needed up to 180.
        for index in range(self.feed.count()):
            caption = self.feed.itemAt(index).widget()
            if isinstance(caption, _Caption):
                caption.setMinimumHeight(
                    caption.heightForWidth(min(room, caption.maximumWidth())))
        height = self.feed.heightForWidth(width)
        if height > 0:
            body.setMinimumHeight(max(height, self.feed.minimumSize().height()))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.refit()

    def _grew(self, _low: int, high: int) -> None:
        if self.following:
            self.verticalScrollBar().setValue(high)


class _Caption(QWidget):
    def heightForWidth(self, width: int) -> int:  # noqa: N802
        # The feed's layout asks at the feed's width, but a caption is never
        # wider than its maximum. Asked at 688 and laid out at 640, a long
        # German sentence got the height of two lines and wrapped to three:
        # its last line was drawn under its own translation.
        return super().heightForWidth(min(width, self.maximumWidth()))

    def __init__(self, line: Line, conversation: bool) -> None:
        super().__init__()
        clear_fill(self)
        self.setMaximumWidth(640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        align = Qt.AlignLeft
        if conversation and line.speaker and line.speaker.endswith("B"):
            align = Qt.AlignRight
        if conversation and line.speaker:
            tag = glass.eyebrow(line.speaker)
            tag.setAlignment(align)
            layout.addWidget(tag)
        shown = (line.original + " " + line.partial).strip() or "…"
        original = glass.label(shown, 25, 600, theme.PRIMARY, wrap=True)
        original.setAlignment(align)
        layout.addWidget(original)
        if line.translated:
            translated = glass.label(line.translated, 15, 400, 0.72, wrap=True)
            translated.setAlignment(align)
            layout.addWidget(translated)
        if line.partial_translated:
            # Lighter than the settled translation, because it will change.
            # The same hand the original's provisional tail is drawn in.
            coming = glass.label(line.partial_translated, 15, 400, 0.45, wrap=True)
            coming.setAlignment(align)
            layout.addWidget(coming)
