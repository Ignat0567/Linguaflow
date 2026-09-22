"""Defaults. The language pair here is the same pair everywhere else."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from lt_core import languages
from lt_core.mt.cloud import LLM_SERVICES, ONLINE_SERVICES
from lt_core.mt.types import TranslationMode

from .. import glass, keys as keys_module, theme
from ..i18n import _, UI_LANGUAGE_NAMES, UI_LANGUAGES, language_name
from ..store import ROOT, display_name
from ..glass import GlassInput
from ..keys import KeyStore
from ..paths import actual_location, default_output_dir
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
#:
#: Raised from 30 after adding the key field: at 30 the descenders were being
#: shaved, and a comma clipped at the bottom reads as a full stop.
_ROW_HEIGHT = 34


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

        voice.body.addWidget(glass.label(
            _("Чем сокращать"), 12, 500, theme.TERTIARY
        ))
        self._shortener = ChipGroup(
            (("", _("Только правила")), ("nvidia", "NVIDIA"), ("groq", "Groq"),
             ("openai", "OpenAI"), ("local", _("Свой сервер"))),
            voice,
        )
        self._shortener.changed.connect(self._sync_shortener)
        voice.body.addWidget(self._shortener)

        key_row = QHBoxLayout()
        key_row.setSpacing(10)
        self._key = GlassInput(voice, placeholder=_("Ключ доступа"))
        self._key.setEchoMode(QLineEdit.Password)
        self._key.editingFinished.connect(self._save_key)
        key_row.addWidget(self._key, 1)
        self._check = glass.GlassButton(_("Проверить"), voice, height=34)
        self._check.clicked.connect(self._check_key)
        key_row.addWidget(self._check)
        self._key_wrap = QWidget()
        clear_fill(self._key_wrap)
        # The field is 34 high and its border is drawn on the edge; a row
        # of exactly 34 clips the bottom line off. The slack is the fix.
        self._key_wrap.setMinimumHeight(_ROW_HEIGHT + 8)
        self._key_wrap.setLayout(key_row)
        voice.body.addWidget(self._key_wrap)
        self._key_note = glass.label("", 12, 400, theme.TERTIARY, wrap=True)
        voice.body.addWidget(self._key_note)

        self._voice_note = glass.label("", 12, 400, theme.TERTIARY, wrap=True)
        voice.body.addWidget(self._voice_note)

        words = SettingsGroup(_("Слова из записи"))
        words.body.addWidget(glass.label(
            _("Имена, термины, названия — через запятую. Распознавание "
              "подсказки не выдумывает, но с ними реже ошибается в том, "
              "что слышит впервые."),
            12, 400, theme.TERTIARY, wrap=True,
        ))
        self._terms = GlassInput(
            words, placeholder=_("например: Kubernetes, Anthropic")
        )
        self._terms.editingFinished.connect(self._save_terms)
        terms_row = QHBoxLayout()
        terms_row.setContentsMargins(0, 0, 0, 0)
        terms_row.addWidget(self._terms, 1)
        self._terms_wrap = QWidget()
        clear_fill(self._terms_wrap)
        # The field's border is drawn on its edge; a row of exactly its height
        # clips the bottom line off, the same way the key row did.
        self._terms_wrap.setMinimumHeight(_ROW_HEIGHT + 8)
        self._terms_wrap.setLayout(terms_row)
        words.body.addWidget(self._terms_wrap)

        fmt = SettingsGroup(_("Формат субтитров"))
        self._format = ChipGroup((
            ("srt", "SRT"), ("vtt", "VTT"), ("txt", "TXT"),
        ), fmt)
        self._format.changed.connect(self._sync_format)
        fmt.body.addWidget(self._format)
        self._format_note = glass.label("", 12, 400, theme.TERTIARY, wrap=True)
        fmt.body.addWidget(self._format_note)

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
        self._where_state = glass.label("", 12, 400, theme.TERTIARY, wrap=True)
        where_files.body.addWidget(self._where_state)

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 0, 8, 8)
        column.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        column.addWidget(title)
        column.addSpacing(28)
        for group in (langs, voice, words, fmt, where_files, where,
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
        self._shortener.set_value(settings.shorten_with)
        self._show_key()
        self._show_folder()
        self._terms.setText(settings.terms)
        self._format.set_value(settings.sub_format)
        self._show_format()
        self._mode.set_value(settings.translation_mode)
        self._service.set_value(settings.online_service)
        self._service.setVisible(settings.translation_mode == TranslationMode.ONLINE)
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

    def _save_terms(self) -> None:
        self.app.store.settings.terms = self._terms.text().strip()
        self._save()

    def _sync_format(self, value: str) -> None:
        self.app.store.settings.sub_format = value
        self._save()
        self._show_format()

    def _sync_mode(self, value: str) -> None:
        self.app.store.settings.translation_mode = value
        self._service.setVisible(value == TranslationMode.ONLINE)
        self._save()

    def _sync_service(self, value: str) -> None:
        self.app.store.settings.online_service = value
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
        self._folder.setText(chosen or str(default_output_dir()))
        real, redirected = actual_location(self.app.store.root)
        note = _("Настройки, история и ключ: {path}", path=str(real))
        if redirected:
            note += " " + _("(система перенаправила эту папку)")
        self._where_state.setText(note)

    def _choose_folder(self) -> None:
        start = self.app.store.settings.output_dir or str(ROOT)
        chosen = QFileDialog.getExistingDirectory(
            self, _("Выберите папку для готовых файлов"), start
        )
        if not chosen:
            return
        self.app.store.settings.output_dir = chosen
        self.app.store.save_settings()
        self._show_format()
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

    def _show_format(self) -> None:
        """Say what the chosen format is for.

        Three acronyms with nothing to distinguish them is a guess, and the
        choice decides whether the file opens in a player, in a browser or in
        a text editor.
        """
        self._format_note.setText({
            "srt": _("SRT — субтитры с таймингом. Понимают плееры, YouTube и "
                     "монтажные программы. Обычный выбор."),
            "vtt": _("VTT — то же самое для веба: HTML5-видео и браузерные "
                     "плееры."),
            "txt": _("TXT — только текст, без времени. Для чтения и "
                     "копирования, не для показа поверх видео."),
        }.get(self.app.store.settings.sub_format, ""))

    def _sync_shortener(self, service: str) -> None:
        self.app.store.settings.shorten_with = service
        self.app.store.save_settings()
        self._show_key()

    # -- the user's own key ----------------------------------------------
    def _show_key(self) -> None:
        """Show whether a key is stored, never the key itself."""
        service = self.app.store.settings.shorten_with
        visible = bool(service) and service != "local"
        self._key_wrap.setVisible(visible)
        self._key_note.setVisible(visible)
        if not visible:
            return

        stored = self.app.store.keys.get(service)
        self._key.setText(stored)
        self._key.setPlaceholderText(
            _("Ключ сохранён: {key}", key=KeyStore.masked(stored)) if stored
            else _("Ключ доступа")
        )
        where = LLM_SERVICES.get(service)
        if keys_module.protection() == "dpapi":
            how = _("Ключ хранится только на этом компьютере и зашифрован "
                    "вашей учётной записью Windows.")
        else:
            how = _("Ключ хранится только на этом компьютере, открытым текстом "
                    "— система не предлагает шифрования.")
        if where is not None:
            how += " " + _("Получить: {where}", where=where.where_to_get_a_key)
        self._key_note.setText(how)

    def _save_key(self) -> None:
        service = self.app.store.settings.shorten_with
        if service:
            self.app.store.keys.set(service, self._key.text())

    def _check_key(self) -> None:
        """Ask the service a real question, so the answer means something."""
        service = self.app.store.settings.shorten_with
        if not service:
            return
        self._save_key()
        if service != "local" and not self.app.store.keys.get(service):
            # Better than letting the provider refuse: its message names
            # `--api-key` and an environment variable, which is the command
            # line talking inside a window that has a field for this.
            self._key_note.setText(_("Введите ключ в поле выше."))
            return
        self._key_note.setText(_("Проверяю…"))
        self._check.setEnabled(False)
        QApplication.processEvents()
        try:
            from lt_core.mt.cloud import build_cloud_provider

            key = self.app.store.keys.get(service)
            provider = build_cloud_provider(
                service=service, **({"api_key": key} if key else {})
            )
            answer = provider.shorten([("Это довольно длинная проверочная "
                                        "строка, которую надо сократить.", 25)],
                                      "ru")
            ok = bool(answer and answer[0].strip())
            self._key_note.setText(
                _("Ключ работает, модель отвечает.") if ok
                else _("Сервис ответил, но ничего не прислал.")
            )
        except Exception as error:  # noqa: BLE001 -- any failure is the answer
            self._key_note.setText(str(error))
        finally:
            self._check.setEnabled(True)

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
                "Язык перевода — {language}. Мужские реплики читает мужской "
                "голос, женские — женский. Кто говорит, определяется по "
                "высоте голоса в оригинале, отдельно для каждой реплики.",
                language=spoken,
            ))
        else:
            self._voice_note.setText(_(
                "Язык перевода — {language}. Всё читает один голос.",
                language=spoken,
            ))
