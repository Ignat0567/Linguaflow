"""Live translation: one microphone, subtitles as the speaker talks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from lt_core.subtitles.export import to_srt, write
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


class RealtimeScreen(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        clear_fill(self)
        self._lines: list[Line] = []
        self._current = Line()
        self._pending_start = False
        self._ever = False
        self._saved: Path | None = None

        self._pair = LanguagePair(self, compact=True)
        self._pair.changed.connect(self._sync_pair)
        self._modes = ChipGroup((
            ("subtitles", _("Субтитры")),
            ("voice", _("Текст + озвучка")),
            ("conversation", _("Разговор")),
        ), self, stretch=False)
        self._modes.changed.connect(self._sync_mode)
        mode_pill = glass.GlassPanel(self, radius=theme.RADIUS_PILL)
        mode_pill.setFixedHeight(42)
        mode_row = QHBoxLayout(mode_pill)
        mode_row.setContentsMargins(8, 4, 8, 4)
        mode_row.setSpacing(0)
        mode_row.addWidget(self._modes)

        controls = QHBoxLayout()
        controls.setSpacing(16)
        controls.addStretch()
        controls.addWidget(self._pair)
        controls.addWidget(mode_pill)
        controls.addStretch()

        self._record = glass.RecordButton(self)
        self._record.toggled.connect(self._toggled)
        self._status = glass.label(
            _("Нажмите, чтобы начать запись"), 13, 400, 0.70
        )
        self._status.setAlignment(Qt.AlignCenter)

        self._panel = glass.GlassPanel(self, radius=theme.RADIUS_PANEL)
        self._panel.setMinimumHeight(200)
        self._panel.setMaximumWidth(760)
        self._feed = QVBoxLayout(self._panel)
        self._feed.setContentsMargins(32, 28, 32, 28)
        self._feed.setSpacing(18)
        self._feed.setAlignment(Qt.AlignCenter)
        self._placeholder = glass.label(
            _("Нажмите на кнопку, чтобы начать"), 13, 400, theme.MUTED
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
        root.addWidget(self._status, 0, Qt.AlignHCenter)
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

    def _toggled(self, on: bool) -> None:
        if on:
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
        self._status.setText(_("Слушаю…"))
        if self.app.store.settings.overlay:
            self.app.overlay.reveal()
            self.app.overlay.set_caption(listening=True)
        self.app.engine.start_live(self.app.store.settings)

    def _on_fail(self, message: str) -> None:
        self._pending_start = False
        self._status.setText(message)
        self._record.blockSignals(True)
        self._record.setChecked(False)
        self._record.blockSignals(False)

    def _on_stopped(self) -> None:
        self._ever = True
        self._record.blockSignals(True)
        self._record.setChecked(False)
        self._record.blockSignals(False)
        self._status.setText(_("Остановлено"))
        if self._lines or self._current.original:
            self._save.show()
        self._push_overlay()

    def _on_update(self, update) -> None:
        current = self._current
        if update.speaker and current.speaker and update.speaker != current.speaker:
            if current.original or current.translated:
                self._lines.append(current)
            self._current = Line(speaker=update.speaker)
            current = self._current
        if not current.speaker:
            current.speaker = update.speaker
        if update.committed:
            current.original += update.committed
            current.partial = ""
        if update.partial:
            current.partial = update.partial
        if update.translation:
            current.translated = (
                f"{current.translated} {update.translation}".strip()
                if current.translated else update.translation
            )
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
        if self._current.original or self._current.partial:
            visible.append(self._current)
        if not visible:
            placeholder = glass.label(
                _("Нажмите на кнопку, чтобы начать"), 13, 400, theme.MUTED
            )
            placeholder.setAlignment(Qt.AlignCenter)
            self._feed.addWidget(placeholder)
            return
        conversation = self.app.store.settings.realtime_mode == "conversation"
        for line in visible[-8:]:
            self._feed.addWidget(_Caption(line, conversation), 0, Qt.AlignCenter)

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
            translated=line.translated,
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
        cues = []
        cursor = 0.0
        for index, line in enumerate(lines, start=1):
            text = line.translated or line.original
            duration = max(1.2, min(6.0, 0.06 * max(1, len(text))))
            cues.append(Cue(index, cursor, cursor + duration, (text,)))
            cursor += duration
        srt_path = write(folder / "live.srt", to_srt(tuple(cues)))
        body = "\n\n".join(
            (f"[{line.speaker}]\n" if line.speaker else "")
            + line.original
            + (f"\n{line.translated}" if line.translated else "")
            for line in lines
        )
        txt_path = write(folder / "live.txt", body + "\n")
        settings = self.app.store.settings
        worker = self.app.engine.last_live
        duration = worker.audio_seconds if worker else cursor
        self.app.store.add(HistoryEntry(
            id=entry_id, kind="live",
            title=_("Живой перевод"),
            source_language=settings.from_lang,
            target_language=settings.to_lang,
            duration=duration,
            created=datetime.now().isoformat(timespec="seconds"),
            folder=str(folder),
            outputs={"srt": str(srt_path), "txt": str(txt_path)},
        ))
        self.app.history_changed()
        self._saved = folder
        self._status.setText(
            _("Сохранено · {duration}", duration=format_clock(duration))
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


class _Caption(QWidget):
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
