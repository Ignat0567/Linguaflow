"""The embedded browser's machinery: profile, ad blocking, the audio tap.

Measured before this was written (spike/browser_probe.py, adblock_probe.py):

* This QtWebEngine plays VP9/Opus/AV1 and has no H.264/AAC. YouTube works;
  a site that serves only H.264 -- X among them -- shows a player that never
  starts. That is the build, not something this module can fix.
* Tapping the page's <video> through Web Audio yields the video's own sound,
  exactly: a track transcribed through the tap matched the direct
  transcription word for word. So the dub read aloud through the speakers
  never comes back in as speech.
* Without a blocker, 36 of 37.5 seconds played on a YouTube talk were ads,
  in the same <video>. They would have been translated and read out. Network
  filtering alone blocked 6 requests and no ads (they come from the same
  servers as the video); pruning the ad fields out of the player's response
  took it to 0 s in 3 of 3 runs.
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)

HOME_URL = "https://www.youtube.com/"
SEARCH_URL = "https://www.youtube.com/results?search_query={}"

#: The tap and its drain run here, not in the page's own world: the page can
#: neither see nor break them, and they cannot collide with its globals.
TAP_WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld

#: How often the page is drained. Also the upper bound on what the tap adds
#: to the delay before a word reaches the recogniser.
DRAIN_MS = 200


# -- the address bar -----------------------------------------------------

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
_HOSTLIKE = re.compile(r"^(localhost|[\w-]+(\.[\w-]+)+)(:\d+)?(/.*)?$", re.I)


def address_to_url(text: str) -> QUrl | None:
    """What a line typed into the address bar means.

    A URL is opened as typed; something that looks like a host gets https;
    anything else is a search. The search is YouTube's, because finding a
    video to watch is what this browser is for.
    """
    typed = (text or "").strip()
    if not typed:
        return None
    if _SCHEME.match(typed):
        return QUrl(typed)
    if " " not in typed and _HOSTLIKE.match(typed):
        return QUrl("https://" + typed)
    return QUrl(SEARCH_URL.format(urllib.request.quote(typed)))


# -- ad blocking ---------------------------------------------------------

#: What uBlock Origin's YouTube rules do, written out. The player learns
#: about ads from these fields of its player response, which arrives inline
#: (ytInitialPlayerResponse) or from /youtubei/v1/player through fetch and
#: JSON.parse. Removed on the way in, there is no ad to play. An ad that
#: starts anyway is skipped. Runs in the page's world at document creation,
#: before any of the page's scripts.
YOUTUBE_ADS_JS = r"""
(() => {
  if (!/(^|\.)youtube\.com$/.test(location.hostname)) return;
  const KEYS = ['adPlacements', 'playerAds', 'adSlots', 'adBreakHeartbeatParams'];
  const prune = (o) => {
    if (!o || typeof o !== 'object') return o;
    for (const k of KEYS) if (k in o) delete o[k];
    if (o.playerResponse) prune(o.playerResponse);
    return o;
  };
  const parse = JSON.parse;
  JSON.parse = function (...args) { return prune(parse.apply(this, args)); };
  const json = Response.prototype.json;
  Response.prototype.json = function (...args) { return json.apply(this, args).then(prune); };
  let initial;
  Object.defineProperty(window, 'ytInitialPlayerResponse', {
    configurable: true,
    get() { return initial; },
    set(v) { initial = prune(v); },
  });
  setInterval(() => {
    const player = document.querySelector('.html5-video-player.ad-showing');
    if (!player) return;
    const skip = document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern');
    if (skip) skip.click();
    const v = player.querySelector('video');
    if (v && isFinite(v.duration)) v.currentTime = v.duration;
  }, 300);
})();
"""

FILTER_LISTS = {
    "easylist.txt": "https://easylist.to/easylist/easylist.txt",
    "ubo-filters.txt": "https://ublockorigin.github.io/uAssets/filters/filters.txt",
    "ubo-quick-fixes.txt": "https://ublockorigin.github.io/uAssets/filters/quick-fixes.txt",
}

#: Lists older than this are fetched again, in the background.
FILTER_MAX_AGE = 4 * 24 * 3600

_REQUEST_TYPES = {
    QWebEngineUrlRequestInfo.ResourceType.ResourceTypeMainFrame: "document",
    QWebEngineUrlRequestInfo.ResourceType.ResourceTypeSubFrame: "subdocument",
    QWebEngineUrlRequestInfo.ResourceType.ResourceTypeStylesheet: "stylesheet",
    QWebEngineUrlRequestInfo.ResourceType.ResourceTypeScript: "script",
    QWebEngineUrlRequestInfo.ResourceType.ResourceTypeImage: "image",
    QWebEngineUrlRequestInfo.ResourceType.ResourceTypeFontResource: "font",
    QWebEngineUrlRequestInfo.ResourceType.ResourceTypeMedia: "media",
    QWebEngineUrlRequestInfo.ResourceType.ResourceTypeXhr: "xmlhttprequest",
    QWebEngineUrlRequestInfo.ResourceType.ResourceTypePing: "ping",
    QWebEngineUrlRequestInfo.ResourceType.ResourceTypeCspReport: "csp_report",
}


def fetch_filter_lists(folder: Path, max_age: float = FILTER_MAX_AGE) -> list[Path]:
    """Download the lists that are missing or stale; return those on disk.

    A failed download keeps the old copy. No copy at all only means the
    network half of the blocker is off -- YouTube's ads are handled by
    YOUTUBE_ADS_JS, which needs no list.
    """
    folder.mkdir(parents=True, exist_ok=True)
    for name, url in FILTER_LISTS.items():
        path = folder / name
        if path.exists() and time.time() - path.stat().st_mtime < max_age:
            continue
        # easylist.to answers Python's default User-Agent with 403.
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Linguaflow"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
            partial = path.with_suffix(".part")
            partial.write_bytes(body)
            partial.replace(path)
        except Exception:  # noqa: BLE001 -- offline, blocked, moved: keep the old one
            continue
    return [folder / name for name in FILTER_LISTS if (folder / name).exists()]


def build_blocker(lists: list[Path]):
    """An adblock-rust engine over the given lists, or None without them."""
    if not lists:
        return None
    try:
        import adblock
    except ImportError:
        return None
    filters = adblock.FilterSet()
    for path in lists:
        filters.add_filter_list(path.read_text(encoding="utf-8", errors="replace"))
    return adblock.Engine(filters, optimize=True)


class AdInterceptor(QWebEngineUrlRequestInterceptor):
    """Refuses requests the filter lists name. Runs on Qt's network thread."""

    def __init__(self, engine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.blocked = 0

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:  # noqa: N802
        url = info.requestUrl().toString()
        if not url.startswith("http"):
            return
        kind = _REQUEST_TYPES.get(info.resourceType(), "other")
        source = info.firstPartyUrl().toString() or url
        try:
            matched = self.engine.check_network_urls(url, source, kind).matched
        except Exception:  # noqa: BLE001 -- a filter bug must not break browsing
            return
        if matched:
            self.blocked += 1
            info.block(True)


# -- the profile ---------------------------------------------------------

_profiles: dict[str, QWebEngineProfile] = {}


def browser_profile(root: Path) -> QWebEngineProfile:
    """One on-disk profile per data folder, kept for the life of the process.

    On disk so that signing in, and the answer given to a site's consent
    dialog, are remembered between sessions. Shared because pages outlive the
    widgets that show them: the window rebuilds its screens when the
    interface language changes.
    """
    key = str(Path(root).resolve())
    profile = _profiles.get(key)
    if profile is not None:
        return profile
    storage = Path(root) / "browser"
    from PySide6.QtWidgets import QApplication

    profile = QWebEngineProfile("linguaflow", QApplication.instance())
    profile.setPersistentStoragePath(str(storage / "profile"))
    profile.setCachePath(str(storage / "cache"))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )
    # A video opened from the address bar should start; and the tap's audio
    # context must run without waiting for a click inside the page.
    profile.settings().setAttribute(
        QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False
    )
    script = QWebEngineScript()
    script.setName("linguaflow-youtube-ads")
    script.setSourceCode(YOUTUBE_ADS_JS)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(True)
    profile.scripts().insert(script)
    _profiles[key] = profile
    _start_blocker(profile, storage / "filters")
    return profile


def _start_blocker(profile: QWebEngineProfile, folder: Path) -> None:
    """Fetch and compile the lists off the GUI thread, then install."""
    holder = QObject(profile)

    class _Relay(QObject):
        ready = Signal(object)

    relay = _Relay(holder)

    def install(engine) -> None:
        if engine is None:
            return
        interceptor = AdInterceptor(engine, profile)
        profile.setUrlRequestInterceptor(interceptor)
        profile.setProperty("linguaflow_blocker", True)

    relay.ready.connect(install)

    def work() -> None:
        try:
            relay.ready.emit(build_blocker(fetch_filter_lists(folder)))
        except Exception:  # noqa: BLE001
            relay.ready.emit(None)

    threading.Thread(target=work, name="adblock-lists", daemon=True).start()


# -- the audio tap -------------------------------------------------------

#: Hooks every <video> on the page into Web Audio, once each. The video still
#: plays through the speakers; a second branch copies it, downmixed to mono,
#: into a buffer the drain collects. A paused or muted element adds nothing,
#: so a feed full of silent previews does not bury the one that plays.
TAP_JS = r"""
(() => {
  const lf = window.__lf || (window.__lf = {on: false, chunks: [], rate: 0, taps: 0, error: ''});
  if (!lf.on) return lf.taps;
  for (const v of document.querySelectorAll('video')) {
    if (v.__lfTap) continue;
    try {
      const ctx = new AudioContext();
      const src = ctx.createMediaElementSource(v);
      const gain = ctx.createGain();
      src.connect(gain);
      gain.connect(ctx.destination);
      const proc = ctx.createScriptProcessor(4096, 2, 1);
      const silent = ctx.createGain();
      silent.gain.value = 0;
      src.connect(proc);
      proc.connect(silent);
      silent.connect(ctx.destination);
      proc.onaudioprocess = (e) => {
        if (!lf.on || v.paused || v.muted) return;
        const a = e.inputBuffer.getChannelData(0);
        const b = e.inputBuffer.numberOfChannels > 1 ? e.inputBuffer.getChannelData(1) : a;
        const pcm = new Int16Array(a.length);
        for (let i = 0; i < a.length; i++) {
          pcm[i] = Math.max(-1, Math.min(1, (a[i] + b[i]) / 2)) * 32767;
        }
        lf.rate = ctx.sampleRate;
        lf.chunks.push(pcm);
        if (lf.chunks.length > 400) lf.chunks.shift();
      };
      v.addEventListener('play', () => ctx.resume());
      ctx.resume();
      v.__lfTap = {ctx, gain};
      lf.taps++;
    } catch (e) {
      lf.error = String(e);
    }
  }
  return lf.taps;
})()
"""

DRAIN_JS = r"""
(() => {
  const lf = window.__lf;
  const player = document.querySelector('.html5-video-player');
  const playing = [...document.querySelectorAll('video')].some(v => !v.paused && !v.muted);
  const out = {
    taps: lf ? lf.taps : 0,
    rate: lf ? lf.rate : 0,
    ad: !!(player && player.classList.contains('ad-showing')),
    playing,
    error: lf ? lf.error : '',
    pcm: '',
  };
  if (lf && lf.chunks.length) {
    let total = 0;
    for (const c of lf.chunks) total += c.length;
    const all = new Int16Array(total);
    let at = 0;
    for (const c of lf.chunks) { all.set(c, at); at += c.length; }
    lf.chunks = [];
    const bytes = new Uint8Array(all.buffer);
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    out.pcm = btoa(s);
  }
  return JSON.stringify(out);
})()
"""


def switch_js(on: bool) -> str:
    return (
        "(() => { const lf = window.__lf || (window.__lf = "
        "{on: false, chunks: [], rate: 0, taps: 0, error: ''});"
        f" lf.on = {'true' if on else 'false'}; lf.chunks = []; return lf.taps; }})()"
    )


def decode_drain(result: str) -> tuple[dict, np.ndarray]:
    """The drain's JSON: its state, and the PCM it carried as int16."""
    state = json.loads(result) if result else {}
    raw = state.pop("pcm", "") or ""
    pcm = np.frombuffer(base64.b64decode(raw), dtype=np.int16) if raw else np.zeros(0, np.int16)
    return state, pcm


class PageTap(QObject):
    """Moves one page's video audio into a PageAudioSource while running.

    `state` reports what the viewer should be told: "waiting" (no video is
    playing), "listening", or "ad" (an ad is playing and is not being heard).
    """

    state = Signal(str)

    def __init__(self, page: QWebEnginePage, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.page = page
        self.source = None
        self._state = ""
        self._timer = QTimer(self)
        self._timer.setInterval(DRAIN_MS)
        self._timer.timeout.connect(self._tick)
        # A new document forgets the switch; say it again on every load.
        page.loadFinished.connect(self._reassert)

    @property
    def running(self) -> bool:
        return self.source is not None

    def start(self, source) -> None:
        self.source = source
        self._state = ""
        self.page.runJavaScript(switch_js(True), TAP_WORLD)
        self._timer.start()
        self._tick()

    def stop(self) -> None:
        self._timer.stop()
        self.source = None
        try:
            self.page.runJavaScript(switch_js(False), TAP_WORLD)
        except RuntimeError:  # the page is already gone
            pass

    def _reassert(self, _ok: bool) -> None:
        if self.running:
            self.page.runJavaScript(switch_js(True), TAP_WORLD)

    def _tick(self) -> None:
        if not self.running:
            return
        self.page.runJavaScript(TAP_JS, TAP_WORLD)
        self.page.runJavaScript(DRAIN_JS, TAP_WORLD, self._drained)

    def _drained(self, result) -> None:
        source = self.source
        if source is None or not isinstance(result, str):
            return
        state, pcm = decode_drain(result)
        source.set_gated(bool(state.get("ad")))
        if pcm.size and state.get("rate"):
            source.push(pcm, int(state["rate"]))
        if state.get("ad"):
            now = "ad"
        elif state.get("playing"):
            now = "listening"
        else:
            now = "waiting"
        if now != self._state:
            self._state = now
            self.state.emit(now)
