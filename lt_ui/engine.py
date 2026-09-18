"""Background work the window must not do on the GUI thread.

Loading Whisper and NLLB takes a couple of seconds and a couple of gigabytes.
A file job can run for minutes. A live session is a loop that never returns
of its own accord. All three happen here, and talk to the screens only
through Qt signals -- which are thread-safe, unlike touching a widget.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from lt_core.asr.transcriber import Transcriber, TranscribeOptions, UnsupportedLanguage
from lt_core.audio.capture import CaptureError, open_source
from lt_core.audio.devices import default_device, list_capture_devices
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

from .store import MODEL_ROOT, ROOT, Settings, display_name


class LoadWorker(QThread):
    """Load the recogniser and translator once, keep them for the session."""

    failed = Signal(str)

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.transcriber: Transcriber | None = None
        self.translator = None

    def run(self) -> None:
        try:
            bootstrap(MODEL_ROOT)
            self.transcriber = Transcriber(model_root=MODEL_ROOT)
            options: dict = {}
            if self.settings.translation_mode == TranslationMode.ONLINE:
                options["service"] = self.settings.online_service
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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.settings = settings
        self.transcriber = transcriber
        self.translator = translator
        self.output_dir = output_dir

    def run(self) -> None:
        settings = self.settings
        formats = ["srt", "txt"]
        if settings.sub_format == "vtt":
            formats.append("vtt")

        def on_progress(done: float, total: float) -> None:
            fraction = done / total if total else 0.0
            # Recognition is most of the wall time. Leave the last fifth of
            # the ring for translation and (optionally) the voice track, so
            # the percentage does not sit at 100% while those still run.
            self.progress.emit(min(0.80, fraction * 0.80))

        try:
            result = transcribe_file(
                self.path,
                self.transcriber,
                output_dir=self.output_dir,
                formats=tuple(formats),
                options=TranscribeOptions(
                    language=None if settings.detect_language else settings.from_lang
                ),
                on_stage=self.stage.emit,
                on_progress=on_progress,
                download_dir=ROOT / "downloads",
                translator=self.translator,
                target_language=settings.to_lang,
                bilingual=True,
                voice=settings.voiceover,
                match_voices=settings.match_voices,
                dub_video=settings.dub_video,
                condense=settings.condense,
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

    def __init__(
        self,
        settings: Settings,
        transcriber: Transcriber,
        translator,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.transcriber = transcriber
        self.translator = translator
        self._stop = threading.Event()
        self._source = None
        self.captions: list[LiveUpdate] = []
        self.audio_seconds = 0.0

    def request_stop(self) -> None:
        self._stop.set()
        source = self._source
        if source is not None:
            source.stop()

    def run(self) -> None:
        settings = self.settings
        device = default_device(settings.capture_kind)
        if device is None:
            available = ", ".join(d.label for d in list_capture_devices()[:4]) or "нет"
            self.failed.emit(
                f"Не найдено устройство захвата «{settings.capture_kind}». "
                f"Доступны: {available}."
            )
            return

        speak = settings.realtime_mode == "voice"
        gate = EchoGate() if speak else None
        speaker = None
        if speak:
            try:
                speaker = Speaker(
                    settings.to_lang, voices_dir=MODEL_ROOT / "piper"
                )
            except VoiceError as error:
                self.failed.emit(str(error))
                return
            advice = check_routing(device, None)
            if not advice.safe:
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
                source_language=settings.from_lang,
                target_language=settings.to_lang,
                pace=BALANCED,
            )

        try:
            source = open_source(device)
        except CaptureError as error:
            self.failed.emit(str(error))
            return
        self._source = source

        try:
            for chunk in source.stream():
                if self._stop.is_set():
                    break
                if gate is not None:
                    chunk = gate.filter(chunk)
                produced = session.feed(chunk)
                updates = produced if isinstance(produced, list) else [produced]
                for item in updates:
                    if item is None:
                        continue
                    self.audio_seconds = item.audio_time or self.audio_seconds
                    if item.has_content:
                        self.captions.append(item)
                        self.update.emit(item)
                        if speak and item.translation and speaker is not None:
                            _speak(speaker, item.translation, gate)
        except CaptureError as error:
            self.failed.emit(str(error))
            return
        finally:
            source.stop()
            self._source = None

        if isinstance(session, LiveSession):
            final = session.finish()
            if final.has_content:
                self.captions.append(final)
                self.update.emit(final)
                if speak and final.translation and speaker is not None:
                    _speak(speaker, final.translation, gate)
        self.stopped.emit()


def _speak(speaker: Speaker, text: str, gate: EchoGate | None) -> None:
    """Play a line. Blocks this worker, which is the point: capture continues
    on its own thread, and the echo gate keeps our voice out of the transcript.
    """
    samples, rate = speaker.say(text)
    if samples.size == 0:
        return
    import sounddevice as sd

    duration = len(samples) / rate
    if gate is not None:
        with gate.playing():
            gate.extend(duration)
            sd.play(samples, rate, blocking=True)
    else:
        sd.play(samples, rate, blocking=True)


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

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
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
        worker = LoadWorker(settings, self)
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
            path, settings, self.transcriber, self.translator, output_dir, self
        )
        worker.stage.connect(self.batch_stage)
        worker.progress.connect(self.batch_progress)
        worker.done.connect(self.batch_done)
        worker.failed.connect(self.batch_failed)
        self._batch = worker
        worker.start()

    def start_live(self, settings: Settings) -> None:
        if not self.models_ready:
            self.live_failed.emit("Модели ещё не загружены.")
            return
        if self.live_running:
            return
        worker = LiveWorker(settings, self.transcriber, self.translator, self)
        worker.update.connect(self.live_update)
        worker.failed.connect(self.live_failed)
        worker.stopped.connect(self.live_stopped)
        self._live = worker
        worker.start()

    def stop_live(self) -> None:
        if self._live is not None:
            self._live.request_stop()

    @property
    def last_live(self) -> LiveWorker | None:
        return self._live
