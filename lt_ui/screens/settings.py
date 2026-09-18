"""Defaults. The language pair here is the same pair everywhere else."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from lt_core import languages
from lt_core.mt.cloud import ONLINE_SERVICES
from lt_core.mt.types import TranslationMode

from .. import glass, theme
from ..i18n import _, UI_LANGUAGE_NAMES, UI_LANGUAGES, language_name
from ..store import ROOT, display_name
from ..widgets import (
    AccentSwatch,
    ChipGroup,
    LanguagePair,
    SettingsGroup,
    clear_fill,
)


#: The floor for one row of controls, in pixels.
#:
#: A scroll area that resizes its child to the viewport pays for the extra
#: height out of whatever reports the smallest minimum, and a wrapping label
#: reports nearly none -- so without a floor the toggle rows collapse onto
#: their own captions, which is what a German interface exposed first because
#: its captions are longer.
_ROW_HEIGHT = 30


def _service_labels() -> dict[str, str]:
    """Looked up when the screen is built: a dict at module level would be
    filled at import, before the stored interface language is applied."""
    return {
        "deepl": "DeepL",
        "groq": "Groq",
        "openai": "OpenAI",
        "nvidia": "NVIDIA",
        "local": _("Свой сервер"),
    }


class SettingsScreen(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        clear_fill(self)

        title = glass.label(_("Настройки"), 36, 700, tracking=-2)
        title.setAlignment(Qt.AlignCenter)

        langs = SettingsGroup(_("Языки по умолчанию"))
        self._pair = LanguagePair(langs)
        self._pair.changed.connect(self._sync_pair)
        langs.body.addWidget(self._pair)

        voice = SettingsGroup(_("Голосовой перевод"))
        voice_row = QHBoxLayout()
        voice_row.setSpacing(12)
        self._voice = glass.Toggle(voice)
        self._voice.toggled.connect(self._sync_voice)
        voice_row.addWidget(self._voice)
        voice_row.addWidget(glass.label(_("Озвучивать перевод голосом"), 14))
        voice_row.addStretch()
        langs_voice = QWidget()
        clear_fill(langs_voice)
        langs_voice.setMinimumHeight(_ROW_HEIGHT)
        langs_voice.setLayout(voice_row)
        voice.body.addWidget(langs_voice)

        self._match = glass.Toggle(voice)
        self._match.toggled.connect(self._sync_match)
        voice.body.addWidget(
            self._switch_row(
                self._match, _("Мужской голос мужчинам, женский женщинам")
            )
        )

        self._dub_video = glass.Toggle(voice)
        self._dub_video.toggled.connect(self._sync_dub_video)
        voice.body.addWidget(
            self._switch_row(
                self._dub_video, _("Для видео сохранять копию с новой дорожкой")
            )
        )

        self._condense = glass.Toggle(voice)
        self._condense.toggled.connect(self._sync_condense)
        voice.body.addWidget(
            self._switch_row(
                self._condense, _("Сокращать перевод, чтобы успевал в реплику")
            )
        )

        self._voice_note = glass.label("", 12, 400, theme.TERTIARY, wrap=True)
        voice.body.addWidget(self._voice_note)

        fmt = SettingsGroup(_("Формат субтитров"))
        self._format = ChipGroup((
            ("srt", "SRT"), ("vtt", "VTT"), ("txt", "TXT"),
        ), fmt)
        self._format.changed.connect(self._sync_format)
        fmt.body.addWidget(self._format)

        where = SettingsGroup(_("Где выполняется перевод"))
        self._mode = ChipGroup((
            (TranslationMode.OFFLINE, _("Офлайн")),
            (TranslationMode.ONLINE, _("Онлайн")),
        ), where)
        self._mode.changed.connect(self._sync_mode)
        self._where_note = glass.label(
            _("Офлайн — ничего не покидает компьютер. Онлайн отправляет "
              "текст во внешний сервис, который вы выберете."),
            12, 400, theme.TERTIARY, wrap=True,
        )
        self._service = ChipGroup(
            tuple((key, _service_labels()[key]) for key in ONLINE_SERVICES),
            where,
        )
        self._service.changed.connect(self._sync_service)
        where.body.addWidget(self._mode)
        where.body.addWidget(self._where_note)
        where.body.addWidget(self._service)

        capture = SettingsGroup(_("Источник звука"))
        self._capture = ChipGroup((
            ("microphone", _("Микрофон")),
            ("system", _("Звук системы")),
        ), capture)
        self._capture.changed.connect(self._sync_capture)
        capture.body.addWidget(self._capture)
        capture.body.addWidget(glass.label(
            _("«Звук системы» — то, что играет из колонок, через "
              "WASAPI loopback."),
            12, 400, theme.TERTIARY, wrap=True,
        ))

        overlay = SettingsGroup(_("Окно субтитров"))
        overlay_row = QHBoxLayout()
        overlay_row.setSpacing(12)
        self._overlay = glass.Toggle(overlay)
        self._overlay.toggled.connect(self._sync_overlay)
        overlay_row.addWidget(self._overlay)
        overlay_row.addWidget(glass.label(
            _("Показывать поверх других окон во время записи"), 14
        ))
        overlay_row.addStretch()
        overlay_wrap = QWidget()
        clear_fill(overlay_wrap)
        overlay_wrap.setMinimumHeight(_ROW_HEIGHT)
        overlay_wrap.setLayout(overlay_row)
        overlay.body.addWidget(overlay_wrap)

        share_row = QHBoxLayout()
        share_row.setSpacing(12)
        self._share = glass.Toggle(overlay)
        self._share.toggled.connect(self._sync_share)
        share_row.addWidget(self._share)
        share_row.addWidget(glass.label(
            _("Скрывать с демонстрации экрана (Meet, Zoom)"), 14
        ))
        share_row.addStretch()
        share_wrap = QWidget()
        clear_fill(share_wrap)
        share_wrap.setMinimumHeight(_ROW_HEIGHT)
        share_wrap.setLayout(share_row)
        overlay.body.addWidget(share_wrap)
        overlay.body.addWidget(glass.label(
            _("Окно остаётся у вас на мониторе, но не попадает в полный "
              "экран, которым вы делитесь. Переключается и на самом окне "
              "субтитров, не уходя из звонка. На «поделиться окном» это не "
              "влияет — субтитры и так в другом окне."),
            12, 400, theme.TERTIARY, wrap=True,
        ))

        notify = SettingsGroup(_("Уведомления"))
        notify_row = QHBoxLayout()
        notify_row.setSpacing(12)
        self._notify = glass.Toggle(notify)
        self._notify.toggled.connect(self._sync_notify)
        notify_row.addWidget(self._notify)
        notify_row.addWidget(glass.label(
            _("Поднимать окно, когда файл обработан"), 14
        ))
        notify_row.addStretch()
        notify_wrap = QWidget()
        clear_fill(notify_wrap)
        notify_wrap.setMinimumHeight(_ROW_HEIGHT)
        notify_wrap.setLayout(notify_row)
        notify.body.addWidget(notify_wrap)

        accent = SettingsGroup(_("Акцент"))
        swatches = QHBoxLayout()
        swatches.setSpacing(10)
        self._swatches = QButtonGroup(self)
        self._swatches.setExclusive(True)
        for colour in theme.ACCENT_ALTERNATES:
            chip = AccentSwatch(colour, accent)
            self._swatches.addButton(chip)
            chip.toggled.connect(lambda on, c=colour: on and self._sync_accent(c))
            swatches.addWidget(chip)
        swatches.addStretch()
        accent_wrap = QWidget()
        clear_fill(accent_wrap)
        accent_wrap.setMinimumHeight(_ROW_HEIGHT)
        accent_wrap.setLayout(swatches)
        accent.body.addWidget(accent_wrap)

        look = SettingsGroup(_("Вид"))
        self._light = glass.Toggle(look)
        self._light.toggled.connect(self._sync_appearance)
        look.body.addWidget(self._switch_row(self._light, _("Светлая тема")))
        look.body.addWidget(glass.label(
            _("Язык интерфейса"), 12, 500, theme.TERTIARY
        ))
        self._ui_language = ChipGroup(
            tuple((code, UI_LANGUAGE_NAMES[code]) for code in UI_LANGUAGES), look
        )
        self._ui_language.changed.connect(self._sync_ui_language)
        look.body.addWidget(self._ui_language)

        where_files = SettingsGroup(_("Куда сохранять файлы"))
        folder_row = QHBoxLayout()
        folder_row.setSpacing(12)
        self._folder = glass.label("", 13, 500, theme.SECONDARY, wrap=True)
        self._folder.setMinimumWidth(320)
        folder_row.addWidget(self._folder, 1)
        pick = glass.GlassButton(_("Выбрать папку"), where_files, height=34)
        pick.clicked.connect(self._choose_folder)
        folder_row.addWidget(pick)
        reset = glass.TextLink(_("По умолчанию"), where_files, size=12)
        reset.clicked.connect(self._reset_folder)
        folder_row.addWidget(reset)
        folder_wrap = QWidget()
        clear_fill(folder_wrap)
        folder_wrap.setMinimumHeight(_ROW_HEIGHT)
        folder_wrap.setLayout(folder_row)
        where_files.body.addWidget(folder_wrap)

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 0, 8, 8)
        column.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        column.addWidget(title)
        column.addSpacing(28)
        for group in (langs, voice, fmt, where_files, where, capture,
                      overlay, notify, look, accent):
            group.setMaximumWidth(700)
            column.addWidget(group)
            column.addSpacing(14)
        column.addStretch()

    def refresh(self) -> None:
        settings = self.app.store.settings
        self._pair.set_pair(settings.from_lang, settings.to_lang)
        for toggle, value in (
            (self._voice, settings.voiceover),
            (self._match, settings.match_voices),
            (self._dub_video, settings.dub_video),
            (self._condense, settings.condense),
        ):
            toggle.blockSignals(True)
            toggle.setChecked(value)
            toggle.blockSignals(False)
        self._light.blockSignals(True)
        self._light.setChecked(settings.appearance == theme.LIGHT)
        self._light.blockSignals(False)
        self._ui_language.set_value(settings.ui_language)
        self._show_folder()
        self._format.set_value(settings.sub_format)
        self._mode.set_value(settings.translation_mode)
        self._service.set_value(settings.online_service)
        self._service.setVisible(settings.translation_mode == TranslationMode.ONLINE)
        self._capture.set_value(settings.capture_kind)
        self._overlay.blockSignals(True)
        self._overlay.setChecked(settings.overlay)
        self._overlay.blockSignals(False)
        self._share.blockSignals(True)
        self._share.setChecked(settings.overlay_hidden_from_share)
        self._share.blockSignals(False)
        self._notify.blockSignals(True)
        self._notify.setChecked(settings.notify)
        self._notify.blockSignals(False)
        for button in self._swatches.buttons():
            button.blockSignals(True)
            button.setChecked(button.colour.lower() == settings.accent.lower())
            button.blockSignals(False)
        self._update_voice_note()

    def _save(self) -> None:
        self.app.store.save_settings()
        self.app.settings_changed()

    def _sync_pair(self) -> None:
        source, target = self._pair.pair()
        self.app.store.settings.from_lang = source
        self.app.store.settings.to_lang = target
        self._save()
        self._update_voice_note()

    def _sync_voice(self, on: bool) -> None:
        self.app.store.settings.voiceover = on
        self._save()

    def _sync_format(self, value: str) -> None:
        self.app.store.settings.sub_format = value
        self._save()

    def _sync_mode(self, value: str) -> None:
        self.app.store.settings.translation_mode = value
        self._service.setVisible(value == TranslationMode.ONLINE)
        self._save()

    def _sync_service(self, value: str) -> None:
        self.app.store.settings.online_service = value
        self._save()

    def _sync_capture(self, value: str) -> None:
        self.app.store.settings.capture_kind = value
        self._save()

    def _sync_overlay(self, on: bool) -> None:
        self.app.store.settings.overlay = on
        self._save()
        overlay = getattr(self.app, "overlay", None)
        if overlay is None:
            return
        if on:
            overlay.reveal()
        else:
            overlay.hide()

    def _sync_share(self, hidden: bool) -> None:
        self.app.store.settings.overlay_hidden_from_share = hidden
        self._save()
        overlay = getattr(self.app, "overlay", None)
        if overlay is not None:
            overlay._share.blockSignals(True)
            overlay._share.setChecked(hidden)
            overlay._share.blockSignals(False)
            overlay._on_share(hidden)

    def _sync_notify(self, on: bool) -> None:
        self.app.store.settings.notify = on
        self._save()

    def _sync_accent(self, colour: str) -> None:
        self.app.store.settings.accent = colour
        theme.set_accent(colour)
        self._save()
        window = self.window()
        if window is not None:
            window.update()
            for child in window.findChildren(QWidget):
                child.update()

    def _switch_row(self, toggle: glass.Toggle, caption: str) -> QWidget:
        """A toggle and its caption on one line, like the row above it."""
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(toggle)
        row.addWidget(glass.label(caption, 14))
        row.addStretch()
        holder = QWidget()
        clear_fill(holder)
        holder.setMinimumHeight(_ROW_HEIGHT)
        holder.setLayout(row)
        return holder

    def _show_folder(self) -> None:
        chosen = self.app.store.settings.output_dir
        self._folder.setText(
            chosen or _("Внутри программы, по одной папке на задание")
        )

    def _choose_folder(self) -> None:
        start = self.app.store.settings.output_dir or str(ROOT)
        chosen = QFileDialog.getExistingDirectory(
            self, _("Выберите папку для готовых файлов"), start
        )
        if not chosen:
            return
        self.app.store.settings.output_dir = chosen
        self.app.store.save_settings()
        self._show_folder()

    def _reset_folder(self) -> None:
        self.app.store.settings.output_dir = ""
        self.app.store.save_settings()
        self._show_folder()

    def _sync_appearance(self, light: bool) -> None:
        self.app.store.settings.appearance = theme.LIGHT if light else theme.DARK
        self.app.store.save_settings()
        self.app.apply_appearance()

    def _sync_ui_language(self, code: str) -> None:
        self.app.store.settings.ui_language = code
        self.app.store.save_settings()
        self.app.apply_language()

    def _sync_match(self, on: bool) -> None:
        self.app.store.settings.match_voices = on
        self.app.store.save_settings()
        self._update_voice_note()

    def _sync_condense(self, on: bool) -> None:
        self.app.store.settings.condense = on
        self.app.store.save_settings()

    def _sync_dub_video(self, on: bool) -> None:
        self.app.store.settings.dub_video = on
        self.app.store.save_settings()

    def _update_voice_note(self) -> None:
        code = self.app.store.settings.to_lang
        language = languages.get(code)
        if language is None or not language.piper_voice:
            self._voice_note.setText(_("Для этого языка голос ещё не задан."))
            return

        spoken = language_name(code)
        if self.app.store.settings.match_voices and languages.has_voice_pair(code):
            self._voice_note.setText(_(
                "Язык перевода — {language}. Мужские реплики читает голос "
                "{male}, женские — {female}. Кто говорит, определяется по "
                "высоте голоса в оригинале, отдельно для каждой реплики.",
                language=spoken,
                male=_voice_label(language.piper_male),
                female=_voice_label(language.piper_female),
            ))
        else:
            self._voice_note.setText(_(
                "Язык перевода — {language}. Всё читает один голос, {voice}.",
                language=spoken, voice=_voice_label(language.piper_voice),
            ))


def _voice_label(voice: str) -> str:
    """«ru_RU-ruslan-medium» -> «ruslan».

    Left as the identifier Piper uses rather than prettified. Half of these
    are names a person would recognise (ruslan, irina) and half are corpus
    labels that are not (hfc_male), and «Hfc male» reads worse than the plain
    identifier does.
    """
    parts = voice.split("-")
    return parts[1] if len(parts) > 1 else voice
