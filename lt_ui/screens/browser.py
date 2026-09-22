"""A browser inside the app: watch a video, hear or read it in your language.

Two ways to hear a video, chosen by what this web engine can play:

* A page it plays (YouTube): the page's own <video> is tapped (see
  lt_ui.browser), so the live session hears the video and nothing else.
* A page it cannot (X serves H.264 only; the engine has none): the post's
  video is downloaded with yt-dlp -- carrying the signed-in session, when
  there is one -- and played here in a player of our own (lt_ui.video_player).

Either way the same live session, captions, voice and ducking follow.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lt_core.audio.capture import PageAudioSource
from lt_core.realtime.session import append_committed

from .. import glass, theme
from ..browser import (
    HOME_URL,
    CatchUp,
    PageClock,
    PageTap,
    recorded_video_id,
    address_to_url,
    browser_profile,
    cookie_jar,
    plays_here,
)
from ..i18n import _
from ..widgets import LanguagePair, clear_fill


class _Relay(QObject):
    """Carries 'a line is being spoken' from the voice's thread to this one."""

    speaking = Signal(bool)


class BrowserScreen(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        clear_fill(self)
        self._view = None
        self._page = None
        self._video = None
        self._tap: PageTap | None = None
        self._source: PageAudioSource | None = None
        #: What the voice ducks under: the page tap or the downloaded video.
        self._audio = None
        self._pending_start = False
        #: A downloaded video waiting for the models: (MediaInfo, frames).
        self._pending_video = None
        self._download = None
        #: True while the engine's live session is this screen's. The
        #: realtime screen listens to the same engine signals.
        self._mine = False
        self._original = ""
        self._partial = ""
        self._translated = ""
        self._coming = ""
        # -- translating ahead (a recorded YouTube video) -----------------
        self._clock: PageClock | None = None
        self._ahead_url: QUrl | None = None   # wanted, models or pipeline pending
        self._ahead_id = ""
        self._ahead_worker = None
        self._track = None                    # ready: lines on the video clock
        self._cue_voice = None
        self._relay = _Relay(self)

        # -- toolbar ------------------------------------------------------
        self._back = glass.GlassButton("←", self, size=15, height=34, padding=14)
        self._forward = glass.GlassButton("→", self, size=15, height=34, padding=14)
        self._reload = glass.GlassButton("↻", self, size=15, height=34, padding=14)
        self._address = glass.GlassInput(self, _("Адрес или поиск на YouTube"))
        self._address.returnPressed.connect(self._go)
        self._back.clicked.connect(lambda: self._page and self._view.back())
        self._forward.clicked.connect(lambda: self._page and self._view.forward())
        self._reload.clicked.connect(lambda: self._page and self._view.reload())
        self._overlay_btn = glass.GlassButton(_("Окно субтитров"), self, height=34)
        self._overlay_btn.clicked.connect(self._toggle_overlay)
        # The whole video, the long way: downloaded, transcribed, subtitled
        # and dubbed as files on the file screen.
        self._as_file = glass.GlassButton(_("Скачать и перевести"), self, height=34)
        self._as_file.clicked.connect(self._translate_as_file)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(self._back)
        toolbar.addWidget(self._forward)
        toolbar.addWidget(self._reload)
        toolbar.addWidget(self._address, 1)
        toolbar.addWidget(self._overlay_btn)
        toolbar.addWidget(self._as_file)

        # -- the page or the downloaded video (created on first show) -----
        self._frame = glass.GlassPanel(self, radius=theme.RADIUS_PANEL)
        self._frame.setMinimumHeight(320)
        self._frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(6, 6, 6, 6)
        self._stack = QStackedWidget(self._frame)
        self._stack.setStyleSheet("background: transparent;")
        frame_layout.addWidget(self._stack)

        # -- captions -----------------------------------------------------
        captions = glass.GlassPanel(self, radius=theme.RADIUS_PANEL)
        captions.setFixedHeight(92)
        caption_box = QVBoxLayout(captions)
        caption_box.setContentsMargins(24, 10, 24, 10)
        caption_box.setSpacing(4)
        self._caption = glass.label(
            _("Включите перевод и запустите видео"), 17, 600, theme.PRIMARY, wrap=True
        )
        self._caption.setAlignment(Qt.AlignCenter)
        self._subcaption = glass.label("", 13, 400, 0.62, wrap=True)
        self._subcaption.setAlignment(Qt.AlignCenter)
        caption_box.addWidget(self._caption)
        caption_box.addWidget(self._subcaption)

        # -- controls -----------------------------------------------------
        self._pair = LanguagePair(self, compact=True, allow_auto=True)
        self._pair.changed.connect(self._sync_pair)
        self._translate = glass.Toggle(self)
        self._translate.toggled.connect(self._toggled)
        self._speak = glass.Toggle(self)
        self._speak.toggled.connect(self._sync_voice)
        self._catch_toggle = glass.Toggle(self)
        self._catch_toggle.toggled.connect(self._sync_catch_up)
        self._catch = CatchUp(
            self, self,
            backlog=lambda: self._source.queued_seconds if self._source else 0.0,
        )
        self._catch.held.connect(self._on_held)
        self._status = glass.label("", 12, 400, 0.66, wrap=True)

        controls = QHBoxLayout()
        controls.setSpacing(14)
        controls.addWidget(self._pair)
        controls.addWidget(_pill(_("Переводить видео"), self._translate, self))
        controls.addWidget(_pill(_("Озвучивать"), self._speak, self))
        controls.addWidget(_pill(_("Догонять"), self._catch_toggle, self))
        controls.addWidget(self._status, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 0, 8, 8)
        root.setSpacing(12)
        root.addLayout(toolbar)
        root.addWidget(self._frame, 1)
        root.addWidget(captions)
        root.addLayout(controls)

        engine = app.engine
        engine.ready.connect(self._on_ready)
        engine.failed.connect(self._on_fail)
        engine.live_update.connect(self._on_update)
        engine.live_failed.connect(self._on_fail)
        engine.live_stopped.connect(self._on_stopped)
        engine.live_speaking.connect(self._on_speaking)
        engine.live_lagging.connect(self._on_lagging)

    # -- lifecycle ---------------------------------------------------------
    def refresh(self) -> None:
        settings = self.app.store.settings
        self._pair.set_pair(settings.browser_from_lang, settings.browser_to_lang)
        self._speak.blockSignals(True)
        self._speak.setChecked(settings.realtime_voice)
        self._speak.blockSignals(False)
        self._catch_toggle.blockSignals(True)
        self._catch_toggle.setChecked(settings.browser_catch_up)
        self._catch_toggle.blockSignals(False)
        self._catch.enabled = settings.browser_catch_up
        self._ensure_view()

    def _ensure_view(self) -> None:
        """Start the web engine the first time the screen is shown.

        It is a separate process and costs a second and a few hundred
        megabytes; nobody who never opens this screen should pay for it.
        """
        if self._view is not None:
            return
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView

        from ..video_player import DownloadedVideo

        profile = browser_profile(self.app.store.root)
        self._view = QWebEngineView(self._stack)
        self._page = QWebEnginePage(profile, self._view)
        self._view.setPage(self._page)
        self._view.urlChanged.connect(self._show_url)
        self._stack.addWidget(self._view)
        self._video = DownloadedVideo(self._stack)
        self._video.closed.connect(self._back_to_page)
        self._video.ended.connect(self._video_ended)
        self._stack.addWidget(self._video)
        self._tap = PageTap(self._page, self)
        self._tap.state.connect(self._on_tap_state)
        self._clock = PageClock(self._page, self)
        self._clock.changed.connect(self._ahead_render)
        self._relay.speaking.connect(self._clock.duck)
        last = self.app.store.settings.browser_url
        self._view.load(QUrl(last if last.startswith("http") else HOME_URL))

    def shutdown(self) -> None:
        """Stop translating before the widgets go (language change, quit)."""
        self._stop_ahead("")
        if self._mine or self._pending_start:
            self._pending_start = False
            self.app.engine.stop_live()
        if self._tap is not None:
            self._tap.stop()
        if self._video is not None:
            self._video.stop()

    def open_url(self, url: QUrl) -> None:
        self._ensure_view()
        self._back_to_page()
        self._view.load(url)

    # -- navigation --------------------------------------------------------
    def _go(self) -> None:
        url = address_to_url(self._address.text())
        if url is not None:
            self.open_url(url)
            self._view.setFocus()

    def _show_url(self, url: QUrl) -> None:
        if not self._address.hasFocus():
            self._address.setText(url.toString())
        if url.scheme() in ("http", "https"):
            self.app.store.settings.browser_url = url.toString()
            self.app.store.save_settings()
        if (self._ahead_url is not None or self._track is not None)                 and recorded_video_id(url) != self._ahead_id:
            self._stop_ahead(_("Видео сменилось — включите перевод снова"))
            return
        if not plays_here(url) and not self._mine:
            self._status.setText(_(
                "Видео с этого сайта скачивается перед переводом — "
                "откройте пост и включите перевод"
            ))

    def _back_to_page(self) -> None:
        if self._video is not None and self._stack.currentWidget() is self._video:
            if self._mine and self._audio is self._video:
                self.app.engine.stop_live()
            self._video.stop()
            self._stack.setCurrentWidget(self._view)

    def _translate_as_file(self) -> None:
        if self._view is None:
            return
        url = self._view.url().toString()
        if url.startswith("http"):
            self.app.translate_link(url)

    # -- settings ----------------------------------------------------------
    def _sync_pair(self) -> None:
        source, target = self._pair.pair()
        self.app.store.settings.browser_from_lang = source
        self.app.store.settings.browser_to_lang = target
        self.app.store.save_settings()

    def _live_settings(self):
        """The settings a browser session runs on.

        A video's language is not the viewer's: measured on a German talk
        run as English, Whisper wrote German as English words, looped
        («oder Merck, bereitstellen, oder Merck, bereitstellen»), and the
        first line took 15 s. So the browser detects unless told, and it is
        always one speaker, whatever the Live screen's mode is.
        """
        from dataclasses import replace

        settings = self.app.store.settings
        chosen = settings.browser_from_lang
        return replace(
            settings,
            from_lang="" if chosen in ("", "auto") else chosen,
            to_lang=settings.browser_to_lang,
            realtime_mode="subtitles",
        )

    def _sync_voice(self, on: bool) -> None:
        self.app.store.settings.realtime_voice = on
        self.app.store.save_settings()

    def _sync_catch_up(self, on: bool) -> None:
        self.app.store.settings.browser_catch_up = on
        self.app.store.save_settings()
        self._catch.enabled = on
        if not on:
            self._catch.release()

    # -- translation -------------------------------------------------------
    def _toggled(self, on: bool) -> None:
        if not on and (self._ahead_url is not None or self._track is not None):
            self._stop_ahead(_("Остановлено"))
            return
        if on and self._view is not None and self._stack.currentWidget() is not self._video:
            if recorded_video_id(self._view.url()):
                self._start_ahead(self._view.url())
                return
        if not on:
            self._pending_start = False
            self._pending_video = None
            if self._mine:
                self.app.engine.stop_live()
                self._status.setText(_("Останавливаю…"))
            return
        if self.app.engine.live_running and not self._mine:
            self._refuse(_("Сейчас идёт живой перевод на экране «Реальное время»."))
            return
        self._ensure_view()
        self._pending_start = True
        self._pending_video = None
        self._original = self._partial = self._translated = self._coming = ""
        url = self._view.url()
        if plays_here(url) or self._stack.currentWidget() is self._video:
            if self._stack.currentWidget() is self._video and self._video.sound is not None:
                # The downloaded video is still here: translate it again.
                self._pending_video = ("again", None)
            self._status.setText(_("Загружаю модели…"))
            self.app.engine.prepare(self.app.store.settings)
            return
        self._start_download(url)

    # -- translating a recorded video ahead ---------------------------------
    def _start_ahead(self, url: QUrl) -> None:
        """Hold the video, fetch and translate it whole, then play it on.

        Held so the opening is not missed while the translation is made; the
        page goes on by itself once lines are ready.
        """
        self._ahead_url = url
        self._ahead_id = recorded_video_id(url)
        self._track = None
        self._caption.setText("…")
        self._subcaption.setText("")
        self._clock.start()
        self._clock.hold(True)
        self._status.setText(_("Загружаю модели…"))
        self.app.engine.prepare(self.app.store.settings)

    def _run_ahead(self) -> None:
        from ..ahead import AheadWorker
        from ..store import MODEL_ROOT

        chosen = self.app.store.settings.browser_from_lang
        worker = AheadWorker(
            self._ahead_url.toString(),
            self.app.store.root / "downloads" / "browser-ahead" / self._ahead_id,
            self.app.engine.transcriber,
            self.app.engine.translator,
            None if chosen in ("", "auto") else chosen,
            self.app.store.settings.browser_to_lang,
            self,
            match_voices=self.app.store.settings.match_voices,
            speaker_dir=MODEL_ROOT / "speaker",
        )
        worker.stage.connect(
            lambda stage: self._status.setText(_("Готовлю перевод: {stage}", stage=stage))
        )
        worker.done.connect(self._ahead_ready)
        worker.failed.connect(lambda message: self._stop_ahead(message))
        self._ahead_worker = worker
        worker.start()

    def _ahead_ready(self, track) -> None:
        if self._ahead_url is None:
            return  # switched off meanwhile
        from ..i18n import language_name

        self._track = track
        self._ahead_worker = None
        if self.app.store.settings.realtime_voice and len(track):
            self._cue_voice = self._make_voice(track)
            self._cue_voice.start()
        if self.app.store.settings.overlay:
            self.app.overlay.reveal()
        if {line.voice for line in track.lines} >= {"male", "female"}:
            ready = _("Перевод готов · {language} · {count} фраз · мужской и женский голос")
        else:
            ready = _("Перевод готов · {language} · {count} фраз")
        self._status.setText(ready.format(
            language=language_name(track.language), count=len(track)))
        self._clock.hold(False)

    def _make_voice(self, track):
        import sounddevice as sd

        from lt_core.tts.speaker import Speaker

        from ..ahead import CueVoice, Track, speech_lines
        from ..store import MODEL_ROOT

        language = self.app.store.settings.browser_to_lang
        names = voice_names(language)
        speakers: dict[str, Speaker] = {}

        def speaker_for(gender: str) -> Speaker:
            name = names.get(gender) or names[""]
            if name not in speakers:
                speakers[name] = Speaker(language, voice=name, voices_dir=MODEL_ROOT / "piper")
            return speakers[name]

        def synth(line):
            # Fitted to its own slot, as the file dub does: up to what still
            # sounds like a person, never stretched.
            made = speaker_for(line.voice).fit(
                line.translated, line.start, max(0.5, line.end - line.start))
            return made.samples, made.rate

        # The screen shows lines; the voice reads the sentences they make.
        return CueVoice(
            Track(speech_lines(track), track.language), self._clock.now, synth=synth,
            play=lambda samples, rate: sd.play(samples, rate, blocking=True),
            announce=self._relay.speaking.emit,
        )

    def _ahead_render(self) -> None:
        if self._track is None:
            return
        moment, _playing = self._clock.now()
        line = self._track.at(moment)
        shown = line.translated if line else ""
        original = line.original if line else ""
        self._caption.setText(shown)
        self._subcaption.setText(original)
        overlay = getattr(self.app, "overlay", None)
        if overlay is not None and overlay.isVisible():
            overlay.set_caption(original=original, translated=shown, speaker=None,
                                listening=True)

    def _stop_ahead(self, message: str) -> None:
        if self._ahead_url is None and self._track is None:
            return
        self._ahead_url = None
        self._ahead_id = ""
        if self._ahead_worker is not None:
            self._ahead_worker.cancel()
            self._ahead_worker = None
        if self._cue_voice is not None:
            voice, self._cue_voice = self._cue_voice, None
            voice.stop()
            # A line being read is inside PortAudio until it ends. Left there,
            # quitting the program with the voice on crashed it on the way
            # out (access violation in ntdll): the interpreter was torn down
            # under a thread still playing. Cut the line short and wait for
            # the voice's threads to see the stop.
            try:
                import sounddevice as sd

                sd.stop()
            except Exception:  # noqa: BLE001 -- no audio device: nothing playing
                pass
            voice.join(timeout=3.0)
        self._track = None
        if self._clock is not None:
            self._clock.hold(False)
            self._clock.stop()
        if message:
            self._status.setText(message)
        self._translate.blockSignals(True)
        self._translate.setChecked(False)
        self._translate.blockSignals(False)

    def _start_download(self, url: QUrl) -> None:
        from ..video_player import DownloadWorker

        root = self.app.store.root
        jar = cookie_jar(root)
        cookies = jar.write_for(url, root / "browser" / "download-cookies.txt") if jar else None
        worker = DownloadWorker(url.toString(), root / "downloads" / "browser", cookies, self)
        worker.done.connect(self._downloaded)
        worker.failed.connect(self._download_failed)
        self._download = worker
        self._status.setText(_("Скачиваю видео…"))
        worker.start()

    def _downloaded(self, info, frames) -> None:
        if not self._pending_start:
            return  # switched off while it downloaded
        self._pending_video = (info, frames)
        self._status.setText(_("Загружаю модели…"))
        self.app.engine.prepare(self.app.store.settings)

    def _download_failed(self, message: str) -> None:
        if not self._pending_start:
            return
        self._pending_start = False
        self._finish(message)

    def _on_ready(self) -> None:
        if self._ahead_url is not None and self._ahead_worker is None and self._track is None:
            self._run_ahead()
            return
        if not self._pending_start:
            return
        self._pending_start = False
        self._source = PageAudioSource()
        self._mine = True
        if self.app.store.settings.overlay:
            self.app.overlay.reveal()
            self.app.overlay.set_caption(listening=True)
        pending, self._pending_video = self._pending_video, None
        if pending is None:
            self._audio = self._tap
            self._tap.start(self._source)
            self._status.setText(_("Жду, когда заиграет видео"))
        else:
            info, frames = pending
            if info != "again":
                self._video.load(
                    info.path, frames, 48_000, info.title, on_audio=self._source.push
                )
            else:
                self._video.sound.on_audio = self._source.push
            self._stack.setCurrentWidget(self._video)
            self._audio = self._video
            self._status.setText(_("Слушаю видео"))
        self._heard_language = ""
        self.app.engine.start_live(self._live_settings(), source=self._source)
        if self._audio is self._video:
            self._video.play()

    def _video_ended(self) -> None:
        if self._mine and self._audio is self._video:
            self.app.engine.stop_live()

    def _on_speaking(self, speaking: bool) -> None:
        if self._mine and self._audio is not None:
            self._audio.duck(speaking)
            self._catch.speaking(speaking)

    def _on_lagging(self, seconds: float) -> None:
        if self._mine:
            self._catch.line_lag(seconds)

    def hold(self, held: bool) -> None:
        """CatchUp's target: stop the video and its clock, or go on."""
        if self._source is not None:
            self._source.hold(held)
        if self._audio is not None:
            self._audio.hold(held)

    def _on_held(self, held: bool) -> None:
        if self._mine:
            self._status.setText(
                _("Пауза — перевод догоняет видео") if held else _("Слушаю видео")
            )

    def _on_tap_state(self, state: str) -> None:
        if not self._mine or self._audio is not self._tap:
            return
        if self._catch.holding:
            # The video stands because it was held; «waiting for a video to
            # play» would be telling the viewer to do something.
            return
        self._status.setText({
            "listening": _("Слушаю видео"),
            "ad": _("Идёт реклама — её не перевожу"),
            "waiting": _("Жду, когда заиграет видео"),
        }.get(state, ""))

    def _on_update(self, update) -> None:
        if not self._mine:
            return
        heard = update.speaker_language
        if heard and heard != getattr(self, "_heard_language", "") and not self._catch.holding:
            self._heard_language = heard
            from ..i18n import language_name

            self._status.setText(_("Слушаю видео · {language}", language=language_name(heard)))
        if update.committed:
            self._original = append_committed(self._original, update)
            self._partial = ""
        if update.partial:
            self._partial = update.partial
        self._coming = update.partial_translation
        if update.translation:
            self._translated = update.translation
            self._coming = ""
            self._original = ""
        self._render()

    def _render(self) -> None:
        # The settled sentence, and the next one as it forms, in a lighter
        # hand; the original underneath, trimmed to its latest words.
        shown = self._translated
        if self._coming:
            shown = f"{shown} {self._coming}".strip() if shown else self._coming
        self._caption.setText(_tail(shown, 150) or "…")
        original = f"{self._original} {self._partial}".strip()
        self._subcaption.setText(_tail(original, 140))
        overlay = getattr(self.app, "overlay", None)
        if overlay is not None and overlay.isVisible():
            overlay.set_caption(
                original=original,
                translated=shown,
                speaker=None,
                listening=True,
            )

    def _on_stopped(self) -> None:
        if not self._mine:
            return
        self._finish(_("Остановлено"))

    def _on_fail(self, message: str) -> None:
        if self._ahead_url is not None and self._ahead_worker is None and self._track is None:
            self._stop_ahead(message)  # the models failed to load
            return
        if not (self._mine or self._pending_start):
            return
        self._pending_start = False
        self._pending_video = None
        self._finish(message)

    def _finish(self, message: str) -> None:
        # A video held for the reading goes on when translation ends.
        self._catch.release()
        self._mine = False
        if self._tap is not None:
            self._tap.stop()
        if self._video is not None and self._audio is self._video:
            self._video.pause()
            if self._video.sound is not None:
                self._video.sound.on_audio = None
            self._video.duck(False)
        self._audio = None
        self._source = None
        self._status.setText(message)
        self._translate.blockSignals(True)
        self._translate.setChecked(False)
        self._translate.blockSignals(False)

    def _refuse(self, message: str) -> None:
        self._status.setText(message)
        self._translate.blockSignals(True)
        self._translate.setChecked(False)
        self._translate.blockSignals(False)

    def _toggle_overlay(self) -> None:
        overlay = self.app.overlay
        visible = not overlay.isVisible()
        self.app.store.settings.overlay = visible
        self.app.store.save_settings()
        if visible:
            overlay.reveal()
            self._render()
        else:
            overlay.hide()


def voice_names(language: str) -> dict[str, str]:
    """The Piper voice for "" (unmeasured), "male" and "female" lines.

    The man is the language's own voice where that is a man's -- for Russian
    dmitri, the one listened to and kept over ruslan and denis -- and its
    male voice otherwise (English's own voice is a woman's).
    """
    from lt_core import languages

    single = languages.voice_for(language)
    if not languages.has_voice_pair(language):
        return {"": single}
    female = languages.voice_for(language, "female")
    male = single if single != female else languages.voice_for(language, "male")
    return {"": single, "male": male, "female": female}


def _pill(caption: str, toggle, parent: QWidget) -> QWidget:
    pill = glass.GlassPanel(parent, radius=theme.RADIUS_PILL)
    pill.setFixedHeight(42)
    row = QHBoxLayout(pill)
    row.setContentsMargins(16, 4, 10, 4)
    row.setSpacing(12)
    row.addWidget(glass.label(caption, 13, 500, 0.82))
    row.addWidget(toggle)
    return pill


def _tail(text: str, limit: int) -> str:
    """The end of a long line, cut at a word, for a strip that shows one."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    space = cut.find(" ")
    return "…" + (cut[space + 1:] if 0 <= space < 30 else cut)
