"""Background work the window must not do on the GUI thread.

Loading Whisper and NLLB takes a couple of seconds and a couple of gigabytes.
A file job can run for minutes. A live session is a loop that never returns
of its own accord. All three happen here, and talk to the screens only
through Qt signals -- which are thread-safe, unlike touching a widget.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from lt_core import languages
from lt_core.asr.transcriber import Transcriber, TranscribeOptions, UnsupportedLanguage
from lt_core.audio.capture import CaptureError, open_source
from lt_core.audio.devices import (
    default_device,
    default_playback_name,
    list_capture_devices,
)
from lt_core.audio.echo_gate import EchoGate, check_routing
from lt_core.media import MediaError
from lt_core.mt.translator import build_translator
from lt_core.mt.types import TranslationError, TranslationMode
from lt_core.pipeline.batch import BatchResult, transcribe_file
from lt_core.realtime.conversation import ConversationSession, Side
from lt_core.realtime.session import BALANCED, LiveSession, LiveUpdate
from lt_core.runtime import bootstrap
from lt_core.tts.speaker import Speaker, VoiceError
from lt_core.video.mux import MuxError

from .store import MODEL_ROOT, ROOT, Settings, display_name, split_terms


def _shortener(settings: Settings, keys=None):
    """The service that rewrites over-long lines, if one was chosen.

    A failure here must not cost the recording: without a key the provider
    refuses to construct, and the job goes ahead with the rules alone.
    """
    if not settings.shorten_with:
        return None
    try:
        from lt_core.mt.cloud import build_cloud_provider

        key = keys.get(settings.shorten_with) if keys is not None else ""
        return build_cloud_provider(
            service=settings.shorten_with, **({"api_key": key} if key else {})
        )
    except Exception:  # noqa: BLE001
        return None


class LoadWorker(QThread):
    """Load the recogniser and translator once, keep them for the session."""

    failed = Signal(str)

    def __init__(self, settings: Settings, keys=None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.keys = keys
        self.transcriber: Transcriber | None = None
        self.translator = None

    def run(self) -> None:
        try:
            bootstrap(MODEL_ROOT)
            self.transcriber = Transcriber(model_root=MODEL_ROOT)
            options: dict = {}
            if self.settings.translation_mode == TranslationMode.ONLINE:
                options["service"] = self.settings.online_service
                key = (
                    self.keys.get(self.settings.online_service)
                    if self.keys is not None else ""
                )
                if key:
                    options["api_key"] = key
            self.translator = build_translator(
                self.settings.translation_mode,
                model_root=MODEL_ROOT,
                **options,
            )
        except TranslationError as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 -- surface anything to the UI
            self.failed.emit(f"Не удалось загрузить модели: {error}")


class BatchWorker(QThread):
    stage = Signal(str)
    progress = Signal(float)
    done = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        path: Path,
        settings: Settings,
        transcriber: Transcriber,
        translator,
        output_dir: Path,
        keys=None,
        data_root: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.settings = settings
        self.transcriber = transcriber
        self.translator = translator
        self.output_dir = output_dir
        self.keys = keys
        self.data_root = Path(data_root) if data_root else output_dir.parent

    def run(self) -> None:
        settings = self.settings
        formats = ["srt", "txt"]
        if settings.sub_format == "vtt":
            formats.append("vtt")

        def on_progress(done: float, total: float) -> None:
            fraction = done / total if total else 0.0
            # Recognition is a share of the job, not the whole of it.
            # Translation, speech and muxing come after and can take longer;
            # they have no seconds to report, so the ring holds at 80% and
            # the busy screen keeps moving around it.
            self.progress.emit(min(0.80, fraction * 0.80))

        try:
            result = transcribe_file(
                self.path,
                self.transcriber,
                output_dir=self.output_dir,
                formats=tuple(formats),
                options=TranscribeOptions(
                    language=None if settings.detect_language else settings.from_lang,
                    terms=split_terms(settings.terms),
                ),
                on_stage=self.stage.emit,
                on_progress=on_progress,
                # Scratch for anything fetched from a link. User data: an
                # installed copy cannot write beside its own executable.
                download_dir=self.data_root / "downloads",
                translator=self.translator,
                target_language=settings.to_lang,
                bilingual=True,
                voice=settings.voiceover,
                match_voices=settings.match_voices,
                dub_video=settings.dub_video,
                condense=settings.condense,
                shortener=_shortener(settings, self.keys),
            )
            self.progress.emit(1.0)
            self.done.emit(result)
        except (MediaError, UnsupportedLanguage, TranslationError, VoiceError,
                MuxError) as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error))


class LiveWorker(QThread):
    """Capture loop. Emits LiveUpdate as the session produces them."""

    update = Signal(object)
    failed = Signal(str)
    stopped = Signal()
    #: True while a translated line is being read out, False when it ends.
    #: The browser screen lowers the video under the voice with it.
    speaking = Signal(bool)
    #: How far the reading will trail the video by the end of the line about
    #: to be read: the time it waited for the voice plus its own length, in
    #: seconds, sent as it starts. The browser screen holds the video when
    #: this grows.
    lagging = Signal(float)

    def __init__(
        self,
        settings: Settings,
        transcriber: Transcriber,
        translator,
        parent: QObject | None = None,
        source=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.transcriber = transcriber
        self.translator = translator
        self._stop = threading.Event()
        #: A source someone else opened -- the embedded browser's page audio.
        #: None means the device the settings name.
        self._given = source
        self._source = None
        self.captions: list[LiveUpdate] = []
        self.audio_seconds = 0.0
        #: Session seconds of audio taken in so far. The reader's clock.
        self.heard = 0.0
        #: Lines read aloud, and lines skipped to catch up, this session.
        self.read_lines = 0
        self.skipped_lines = 0

    def request_stop(self) -> None:
        self._stop.set()
        source = self._source
        if source is not None:
            source.stop()

    def run(self) -> None:
        settings = self.settings
        given = self._given
        device = None if given is not None else default_device(settings.capture_kind)
        if given is None and device is None:
            available = ", ".join(d.label for d in list_capture_devices()[:4]) or "нет"
            self.failed.emit(
                f"Не найдено устройство захвата «{settings.capture_kind}». "
                f"Доступны: {available}."
            )
            return

        speak = settings.realtime_voice
        # A page's own audio never contains what the speakers play, so there
        # is no loop to break: no gate, and no refusal over a shared device.
        gate = EchoGate() if speak and given is None else None
        # One voice per language that will be read out. A conversation needs
        # both: what A says is read to B in B's language and the other way
        # round, so a single voice would read half the session in the wrong
        # one.
        voices: dict[str, Speaker] = {}
        if speak:
            wanted = [settings.to_lang]
            if settings.realtime_mode == "conversation":
                wanted.append(settings.from_lang)
            try:
                for code in wanted:
                    # Loaded up front so a missing model is a refusal now
                    # rather than silence in the middle of a conversation.
                    voices[code] = Speaker(code, voices_dir=MODEL_ROOT / "piper")
            except VoiceError as error:
                self.failed.emit(str(error))
                return
            advice = (
                check_routing(device, default_playback_name())
                if device is not None else None
            )
            if advice is not None and not advice.safe:
                self.failed.emit(
                    advice.reason + ((" " + advice.remedy) if advice.remedy else "")
                )
                return

        if settings.realtime_mode == "conversation":
            session = ConversationSession(
                self.transcriber, self.translator,
                Side(settings.from_lang, display_name(settings.from_lang) + " · A"),
                Side(settings.to_lang, display_name(settings.to_lang) + " · B"),
                pace=BALANCED,
            )
        else:
            session = LiveSession(
                self.transcriber,
                translator=self.translator,
                # Empty means detect: the session pins the language it hears.
                source_language=settings.from_lang or None,
                target_language=settings.to_lang,
                pace=BALANCED,
                terms=split_terms(settings.terms),
            )

        if given is not None:
            source = given
        else:
            try:
                source = open_source(device)
            except CaptureError as error:
                self.failed.emit(str(error))
                return
        self._source = source
        reader = _Reader(
            voices, gate, session, clock=lambda: self.heard,
            announce=self.speaking.emit, report=self.lagging.emit,
        ) if speak else None

        try:
            for chunk in source.stream():
                if self._stop.is_set():
                    break
                if gate is not None:
                    chunk = gate.filter(chunk)
                self.heard = chunk.end_time
                produced = session.feed(chunk)
                updates = produced if isinstance(produced, list) else [produced]
                for item in updates:
                    if item is None:
                        continue
                    self.audio_seconds = item.audio_time or self.audio_seconds
                    if item.has_content:
                        self.captions.append(item)
                        self.update.emit(item)
                        if reader is not None:
                            reader.put(item)
        except CaptureError as error:
            self.failed.emit(str(error))
            if reader is not None:
                reader.close(drain=False)
            return
        finally:
            source.stop()
            self._source = None

        # Both kinds of session have a tail: the last words are transcribed
        # and then held for the sentence that never comes. Conversation mode
        # was not asked for its, so the last thing either person said was
        # dropped every time the button was pressed.
        closing = session.finish()
        for final in closing if isinstance(closing, list) else [closing]:
            if not final.has_content:
                continue
            self.captions.append(final)
            self.update.emit(final)
            if reader is not None:
                reader.put(final)
        if reader is not None:
            reader.close(drain=True)
            self.read_lines, self.skipped_lines = reader.read, reader.skipped
        self.stopped.emit()


class _Reader:
    """Reads settled lines aloud on its own thread.

    The live worker used to read each line itself, and while it read it
    heard nothing. The capture queue holds eight seconds; a fast speaker and
    a translation longer than its original fill that, and the oldest audio
    is dropped -- speech never recognised, with nothing on screen to say so.
    Measured on a fast speaker, 60 s with the voice on: 13.8 s lost.

    Here hearing never waits for speaking. What can still fall behind is the
    voice itself, and it is not allowed to fall behind for ever: a line older
    than SKIP_AFTER is not read if a newer one is already waiting. Its text
    stays on screen; only its reading is skipped, so the voice speaks about
    what is being said now rather than about a minute ago.
    """

    #: Seconds a line may have waited before the voice skips it for a newer.
    SKIP_AFTER = 8.0

    def __init__(self, voices: dict[str, Speaker], gate: EchoGate | None,
                 session, clock, announce=None, report=None) -> None:
        self.voices = voices
        self.gate = gate
        self.session = session
        self.clock = clock
        #: Told True/False as each line starts and ends (the browser ducks).
        self.announce = announce
        #: Given how far the reading will trail by the end of each line (the
        #: browser holds the video when it grows).
        self.report = report
        self.read = 0
        self.skipped = 0
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="Reader", daemon=True)
        self._thread.start()

    def put(self, update) -> None:
        if update.translation:
            self._queue.put(update)

    def close(self, drain: bool = True, timeout: float = 60.0) -> None:
        """Stop after the lines already queued (drain) or at once."""
        if not drain:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
        self._queue.put(None)
        self._thread.join(timeout=timeout)

    def _newer_waiting(self) -> bool:
        """A line queued behind this one -- not the stop marker, which is
        not a line and must not cost the last thing said its reading."""
        with self._queue.mutex:
            return any(item is not None for item in self._queue.queue)

    def _run(self) -> None:
        while True:
            update = self._queue.get()
            if update is None:
                return
            behind = max(0.0, self.clock() - (update.audio_time or 0.0))
            if behind > self.SKIP_AFTER and self._newer_waiting():
                self.skipped += 1
                continue
            try:
                _read_out(update, self.voices, self.gate, self.session, behind,
                          self.announce, self.report)
                self.read += 1
            except Exception:  # noqa: BLE001 -- a line that fails is a line unheard
                continue


#: How far the reading may fall behind before it is read faster.
#:
#: Honest about what this buys. Measured on a five-minute talk read aloud, it
#: moved the worst wait from 9.2 s to 8.6 s -- because that wait is one long
#: line being read while the next is already ready, and nothing that keeps the
#: voice human takes more than about 15% off a line.
#:
#: What it does do is keep a session stable. Speech ran to 68% of the audio
#: there, so the queue drained on its own; a pair where the translation is
#: longer than the original, or a speaker who never pauses, would otherwise
#: fall further behind with every line and never recover.
CATCH_UP_AFTER = 1.0


def _read_out(update, voices: dict[str, Speaker], gate: EchoGate | None,
              session, behind: float = 0.0, announce=None, report=None) -> float:
    """Read a settled line out in the language it was translated into.

    Only settled lines: a provisional translation is replaced on the next tick,
    and there is no way to unsay one.

    In a conversation the two sides are read in different registers, so that a
    listener can hear which of them is talking. Two voices a few Hz apart are
    one voice -- measured on a real dialogue, the two languages' default voices
    came out at 179 and 182 Hz.

    `behind` is how long the line has waited for the voice; past
    CATCH_UP_AFTER it is read as fast as a voice still sounds human.
    Returns the seconds it took.
    """
    if not update.translation:
        return 0.0
    language = update.translation_language
    voice = voices.get(language) or next(iter(voices.values()), None)
    if voice is None:
        return 0.0

    register = ""
    if hasattr(session, "register_of") and update.speaker_language:
        register = session.register_of(update.speaker_language)
    wanted = languages.voice_for(language, register) if register else ""
    if wanted and wanted != voice.voice_name:
        chosen = voices.get(wanted)
        if chosen is None:
            try:
                chosen = Speaker(language, voice=wanted,
                                 voices_dir=MODEL_ROOT / "piper")
            except VoiceError:
                # A pair this build does not ship. The language's own voice
                # reads it, which is the fallback everywhere else too.
                chosen = voice
            voices[wanted] = chosen
        voice = chosen

    # Reported once the line is synthesised and its length known: a long
    # line on top of a short wait is as much of a backlog as the reverse.
    before = (lambda length: report(behind + length)) if report is not None else None
    return _speak(voice, update.translation, gate,
                  hurry=behind > CATCH_UP_AFTER, announce=announce, before=before)


def _speak(speaker: Speaker, text: str, gate: EchoGate | None,
           hurry: bool = False, announce=None, before=None) -> float:
    """Play a line; return how long it took. Blocks the reader thread; the
    live worker goes on hearing meanwhile, and the echo gate -- judging by
    when audio was captured -- keeps our voice out of the transcript.

    `hurry` asks for the line as fast as it can still be said, which is how a
    backlog is worked off. `fit` clamps that at the point where the voice stops
    sounding human, so asking for the impossible is safe.

    `announce` is told True as the line starts and False as it ends, whatever
    happens in between. `before` is given the line's length, in seconds,
    just before it is played.
    """
    if hurry:
        utterance = speaker.fit(text, 0.0, 0.01)
        samples, rate = utterance.samples, utterance.rate
    else:
        samples, rate = speaker.say(text)
    if samples.size == 0:
        return 0.0
    import sounddevice as sd

    duration = len(samples) / rate
    if before is not None:
        before(duration)
    if announce is not None:
        announce(True)
    try:
        if gate is not None:
            with gate.playing():
                gate.extend(duration)
                sd.play(samples, rate, blocking=True)
        else:
            sd.play(samples, rate, blocking=True)
    finally:
        if announce is not None:
            announce(False)
    return duration


class Engine(QObject):
    """Owns the loaded models and the currently running job, if any."""

    status = Signal(str)
    ready = Signal()
    failed = Signal(str)

    batch_stage = Signal(str)
    batch_progress = Signal(float)
    batch_done = Signal(object)
    batch_failed = Signal(str)

    live_update = Signal(object)
    live_failed = Signal(str)
    live_stopped = Signal()
    live_speaking = Signal(bool)
    live_lagging = Signal(float)

    def __init__(self, parent: QObject | None = None, keys=None,
                 data_root: Path | None = None) -> None:
        super().__init__(parent)
        #: The user's own API keys, or None when nothing has been entered.
        self.keys = keys
        #: Where this user's data lives; scratch space goes under it.
        self.data_root = Path(data_root) if data_root else ROOT
        self.transcriber: Transcriber | None = None
        self.translator = None
        self._loaded_for: tuple[str, str] | None = None
        self._loader: LoadWorker | None = None
        self._batch: BatchWorker | None = None
        self._live: LiveWorker | None = None

    @property
    def models_ready(self) -> bool:
        return self.transcriber is not None and self.translator is not None

    @property
    def live_running(self) -> bool:
        return self._live is not None and self._live.isRunning()

    @property
    def batch_running(self) -> bool:
        return self._batch is not None and self._batch.isRunning()

    def prepare(self, settings: Settings) -> None:
        """Load models if needed, then emit `ready`.

        Always asynchronous: even a cache hit is delivered on the next tick,
        so callers can connect to `ready` before calling this without racing.
        """
        key = (settings.translation_mode, settings.online_service)
        if self._loaded_for == key and self.models_ready:
            QTimer.singleShot(0, self.ready.emit)
            return
        if self._loader is not None and self._loader.isRunning():
            return
        self.status.emit("Загружаю модели…")
        worker = LoadWorker(settings, self.keys, self)
        worker.failed.connect(self.failed)
        worker.finished.connect(lambda: self._on_loaded(worker, key))
        self._loader = worker
        worker.start()

    def _on_loaded(self, worker: LoadWorker, key: tuple[str, str]) -> None:
        if worker.transcriber is None or worker.translator is None:
            return
        self.transcriber = worker.transcriber
        self.translator = worker.translator
        self._loaded_for = key
        self.ready.emit()

    def start_batch(self, path: Path, settings: Settings, output_dir: Path) -> None:
        if not self.models_ready:
            self.batch_failed.emit("Модели ещё не загружены.")
            return
        if self.batch_running:
            self.batch_failed.emit("Уже идёт обработка файла.")
            return
        worker = BatchWorker(
            path, settings, self.transcriber, self.translator, output_dir,
            self.keys, self.data_root, self,
        )
        worker.stage.connect(self.batch_stage)
        worker.progress.connect(self.batch_progress)
        worker.done.connect(self.batch_done)
        worker.failed.connect(self.batch_failed)
        self._batch = worker
        worker.start()

    def start_live(self, settings: Settings, source=None) -> None:
        """Start a live session on the device the settings name, or on
        `source` when one is given (the embedded browser's page audio)."""
        if not self.models_ready:
            self.live_failed.emit("Модели ещё не загружены.")
            return
        if self.live_running:
            return
        worker = LiveWorker(
            settings, self.transcriber, self.translator, self, source=source
        )
        worker.update.connect(self.live_update)
        worker.failed.connect(self.live_failed)
        worker.stopped.connect(self.live_stopped)
        worker.speaking.connect(self.live_speaking)
        worker.lagging.connect(self.live_lagging)
        self._live = worker
        worker.start()

    def stop_live(self) -> None:
        if self._live is not None:
            self._live.request_stop()

    @property
    def last_live(self) -> LiveWorker | None:
        return self._live
