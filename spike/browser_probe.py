"""Stage 0 of the embedded-browser idea: can QtWebEngine carry it at all?

Two questions decide the whole design, and both are cheap to answer here
before any app code changes:

1. Codecs. pip builds of QtWebEngine usually ship without H.264/AAC. YouTube
   can fall back to VP9/Opus; X serves H.264 and has nothing to fall back to.
2. Clean audio. Hooking the page's <video> into Web Audio gives us only the
   video's sound, so our own dubbing can never leak back into recognition.
   Cross-origin media without CORS comes out as silence, so it has to be
   measured, not assumed.

Usage:
    .venv\\Scripts\\python.exe spike\\browser_probe.py [URL] [--seconds 30]

Writes spike/browser_probe.wav (16 kHz mono) and prints what Whisper heard.
The tapped audio is not routed to the speakers: the probe is silent.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtWebEngineCore import (  # noqa: E402
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# A TED talk: steady English speech from the first seconds. The nocookie embed
# plays without the consent wall a regular watch page shows in the EU.
DEFAULT_URL = "https://www.youtube-nocookie.com/embed/iG9CE55wbtY?autoplay=1"
OUT_WAV = ROOT / "spike" / "browser_probe.wav"

CODECS = {
    "H.264 (mp4/avc1) — X, most sites": 'video/mp4; codecs="avc1.42E01E"',
    "AAC (mp4a)": 'audio/mp4; codecs="mp4a.40.2"',
    "VP9 (webm) — YouTube": 'video/webm; codecs="vp9"',
    "Opus (webm) — YouTube": 'audio/webm; codecs="opus"',
    "AV1": 'video/mp4; codecs="av01.0.05M.08"',
}

CODEC_JS = """
(() => {
  const types = %s;
  const out = {};
  for (const [name, type] of Object.entries(types)) {
    out[name] = {
      mse: !!(window.MediaSource && MediaSource.isTypeSupported(type)),
      element: document.createElement('video').canPlayType(type) || 'no',
    };
  }
  return JSON.stringify(out);
})()
""" % json.dumps(CODECS)

# Installed once the page has a <video>. ScriptProcessor rather than an
# AudioWorklet: a worklet needs addModule(url), which a page's CSP can refuse;
# for a probe the deprecated node is enough. The processor's output is left
# silent, so nothing reaches the speakers.
TAP_JS = """
(() => {
  if (window.__lf) return JSON.stringify({state: 'already'});
  const v = document.querySelector('video');
  if (!v) return JSON.stringify({state: 'no-video'});
  const ctx = new AudioContext();
  const src = ctx.createMediaElementSource(v);
  const proc = ctx.createScriptProcessor(4096, 2, 1);
  const lf = window.__lf = {ctx, chunks: [], frames: 0};
  proc.onaudioprocess = (e) => {
    const a = e.inputBuffer.getChannelData(0);
    const b = e.inputBuffer.numberOfChannels > 1 ? e.inputBuffer.getChannelData(1) : a;
    const pcm = new Int16Array(a.length);
    for (let i = 0; i < a.length; i++) {
      const m = Math.max(-1, Math.min(1, (a[i] + b[i]) / 2));
      pcm[i] = m * 32767;
    }
    lf.chunks.push(pcm);
    lf.frames += a.length;
  };
  src.connect(proc);
  proc.connect(ctx.destination);
  ctx.resume();
  v.muted = false;
  v.play().catch(() => {});
  return JSON.stringify({state: 'tapped', rate: ctx.sampleRate});
})()
"""

PLAY_JS = """
(() => {
  const button = document.querySelector('.ytp-large-play-button');
  if (button) button.click();
  const v = document.querySelector('video');
  if (v) v.play().catch(() => {});
})()
"""

DRAIN_JS = """
(() => {
  const v = document.querySelector('video');
  const lf = window.__lf;
  const info = {
    video: !!v,
    playing: !!(v && !v.paused && v.readyState > 2),
    time: v ? v.currentTime : null,
    error: v && v.error ? v.error.code : null,
    ctx: lf ? lf.ctx.state : null,
    rate: lf ? lf.ctx.sampleRate : null,
    b64: '',
  };
  if (lf && lf.chunks.length) {
    const total = lf.chunks.reduce((n, c) => n + c.length, 0);
    const all = new Int16Array(total);
    let o = 0;
    for (const c of lf.chunks) { all.set(c, o); o += c.length; }
    lf.chunks = [];
    const bytes = new Uint8Array(all.buffer);
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    info.b64 = btoa(s);
  }
  return JSON.stringify(info);
})()
"""


class Probe:
    def __init__(self, app: QApplication, url: str, seconds: float, clean: bool = False) -> None:
        self.app = app
        self.url = url
        self.seconds = seconds
        self.profile = QWebEngineProfile()  # off the record: nothing persists
        settings = self.profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        if clean:
            # Ads play in the same <video> the tap listens to; see adblock_probe.
            from adblock_probe import YT_SCRIPTLET

            script = QWebEngineScript()
            script.setSourceCode(YT_SCRIPTLET)
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            self.profile.scripts().insert(script)
        self.clean = clean
        self.page = QWebEnginePage(self.profile)
        self.view = QWebEngineView()
        self.view.setPage(self.page)
        self.view.resize(960, 600)
        self.view.setWindowTitle("Linguaflow browser probe")
        self.codecs: dict | None = None
        self.rate: int | None = None
        self.pcm: list[np.ndarray] = []
        self.status: dict = {}
        self.tap_state = "not tried"
        self.shot_taken = False
        self.started = time.monotonic()
        self.timer = QTimer()
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick)

    # step 1: codecs, on a neutral https origin with no network needed
    def run(self) -> None:
        self.view.show()
        self.page.loadFinished.connect(self._codecs_page_loaded)
        self.page.setHtml("<html><body>probe</body></html>", QUrl("https://example.com/"))

    def _codecs_page_loaded(self, ok: bool) -> None:
        self.page.loadFinished.disconnect(self._codecs_page_loaded)
        self.page.runJavaScript(CODEC_JS, 0, self._got_codecs)

    def _got_codecs(self, result: str) -> None:
        self.codecs = json.loads(result)
        print("\n== Codecs in this QtWebEngine ==")
        for name, r in self.codecs.items():
            print(f"  {name:36s} MSE={'yes' if r['mse'] else 'NO ':3s}  <video>={r['element']}")
        print(f"\n== Loading {self.url} ==")
        self.page.loadFinished.connect(self._video_page_loaded)
        self.page.load(QUrl(self.url))

    # step 2: tap the page's <video> and drain PCM
    def _video_page_loaded(self, ok: bool) -> None:
        print(f"  page loaded: {ok} {self.page.url().toString()[:80]}")
        if not self.timer.isActive():
            self.started = time.monotonic()
            self.timer.start()

    def _tick(self) -> None:
        elapsed = time.monotonic() - self.started
        # Every tick, not once: a reload (YouTube does one behind its consent
        # dialog) throws the page's tap away. TAP_JS is idempotent.
        self.page.runJavaScript(TAP_JS, 0, self._tapped)
        if self.clean:
            from adblock_probe import REJECT_JS

            self.page.runJavaScript(REJECT_JS, 0)
        if not self.status.get("playing"):
            # The embed's autoplay waits for a click on its own button even
            # when the engine allows playback without a gesture.
            self.page.runJavaScript(PLAY_JS, 0)
        if not self.shot_taken and elapsed > 8:
            self.shot_taken = True
            self.view.grab().save(str(ROOT / "spike" / "browser_probe.png"))
        self.page.runJavaScript(DRAIN_JS, 0, self._drained)
        captured = sum(len(p) for p in self.pcm) / (self.rate or 48000)
        if captured >= self.seconds or elapsed > self.seconds + 45:
            self.timer.stop()
            QTimer.singleShot(300, self._finish)

    def _tapped(self, result: str) -> None:
        info = json.loads(result)
        if info["state"] != self.tap_state:
            print(f"  tap: {info}")
        self.tap_state = info["state"]
        if info.get("rate"):
            self.rate = int(info["rate"])

    def _drained(self, result: str) -> None:
        info = json.loads(result)
        if info["b64"]:
            self.pcm.append(np.frombuffer(base64.b64decode(info["b64"]), dtype=np.int16))
        info.pop("b64")
        if info != self.status:
            print(f"  video: {info}")
            self.status = info

    # step 3: save, measure, transcribe
    def _finish(self) -> None:
        self.view.close()
        self.app.quit()


def summarise(probe: Probe) -> int:
    rate = probe.rate or 48000
    raw = np.concatenate(probe.pcm) if probe.pcm else np.zeros(0, dtype=np.int16)
    audio = raw.astype(np.float32) / 32768.0
    seconds = len(audio) / rate
    rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    print("\n== Captured ==")
    print(f"  {seconds:.1f} s at {rate} Hz, RMS {rms:.4f}, peak {peak:.3f}")
    if seconds < 1 or peak < 1e-3:
        print("  RESULT: silence — the tap got no audio (codec, CORS, or the video never played)")
        return 1

    from lt_core import runtime
    runtime.bootstrap(ROOT / "models")
    from lt_core.audio.resample import StreamResampler
    from lt_core.audio.types import TARGET_SAMPLE_RATE

    resampler = StreamResampler(rate, 1)
    mono16k = resampler.process(audio, last=True)
    with wave.open(str(OUT_WAV), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_SAMPLE_RATE)
        w.writeframes((np.clip(mono16k, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f"  wrote {OUT_WAV}")

    from lt_core.asr.transcriber import Transcriber
    started = time.monotonic()
    transcript = Transcriber(model_root=ROOT / "models").transcribe(mono16k)
    print(f"\n== Whisper heard ({transcript.language}, {time.monotonic() - started:.1f} s) ==")
    print("  " + (transcript.text or "(nothing)"))
    return 0 if transcript.text.strip() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    parser.add_argument("--seconds", type=float, default=45.0)
    parser.add_argument("--clean", action="store_true",
                        help="YouTube: block ads and reject the consent dialog")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    probe = Probe(app, args.url, args.seconds, clean=args.clean)
    probe.run()
    app.exec()
    return summarise(probe)


if __name__ == "__main__":
    raise SystemExit(main())
