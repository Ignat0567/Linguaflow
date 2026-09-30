"""Which ad blocker can the embedded browser actually carry?

Ads on YouTube play in the same <video> the translator listens to, so an
unblocked ad is not just noise on screen: it gets transcribed, translated and
read aloud. Two candidates, measured the same way against no blocker at all:

- ubol: uBlock Origin Lite (MV3), loaded through Qt 6.11's
  QWebEngineExtensionManager. Best YouTube coverage in Chrome, but Qt's
  extension support is new and uBOL leans on declarativeNetRequest,
  scripting and userScripts.
- rust: Brave's adblock-rust (pip `adblock`) behind a
  QWebEngineUrlRequestInterceptor, plus cosmetic CSS and scripts injected
  on load. Entirely ours, but uBO's YouTube scriptlets are not bundled.
- yt: rust plus our own YouTube scriptlet (YT_SCRIPTLET).

Usage:
    .venv\\Scripts\\python.exe spike\\adblock_probe.py none|ubol|rust|yt [URL] [--seconds 40]

The EU consent dialog is dismissed with «reject all». Audio is muted.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "spike" / "_vendor"
UBOL = VENDOR / "ubol"
LISTS = {
    "easylist.txt": "https://easylist.to/easylist/easylist.txt",
    "ubo-filters.txt": "https://ublockorigin.github.io/uAssets/filters/filters.txt",
    "ubo-quick-fixes.txt": "https://ublockorigin.github.io/uAssets/filters/quick-fixes.txt",
}

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtWebEngineCore import (  # noqa: E402
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

DEFAULT_URL = "https://www.youtube.com/watch?v=iG9CE55wbtY"

# «Reject all» in the languages this machine is likely to be served.
REJECT_JS = """
(() => {
  const words = /^(alle ablehnen|reject all|отклонить все|tout refuser)$/i;
  for (const b of document.querySelectorAll('button, tp-yt-paper-button, [role=button]')) {
    const t = (b.innerText || b.getAttribute('aria-label') || '').trim();
    if (words.test(t)) { b.click(); return t; }
  }
  return '';
})()
"""

STATE_JS = """
(() => {
  const v = document.querySelector('video');
  if (v) { v.muted = true; if (v.paused) v.play().catch(() => {}); }
  const player = document.querySelector('#movie_player');
  return JSON.stringify({
    url: location.href.slice(0, 60),
    ad: !!(player && player.classList.contains('ad-showing')),
    playing: !!(v && !v.paused),
    time: v ? Math.round(v.currentTime * 10) / 10 : null,
    duration: v && isFinite(v.duration) ? Math.round(v.duration) : null,
  });
})()
"""

# What uBO's YouTube rules do, written out: the player learns about ads from
# adPlacements/playerAds/adSlots in its player response, which arrives either
# inline (ytInitialPlayerResponse) or from /youtubei/v1/player through
# fetch + JSON.parse. Remove the fields on the way in and there is no ad to
# play. Runs at document creation, before any page script.
YT_SCRIPTLET = r"""
(() => {
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
  // Belt and braces: an ad that still starts is skipped.
  setInterval(() => {
    const player = document.querySelector('#movie_player');
    if (!player || !player.classList.contains('ad-showing')) return;
    const skip = document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern');
    if (skip) skip.click();
    const v = document.querySelector('video');
    if (v && isFinite(v.duration)) v.currentTime = v.duration;
  }, 300);
})();
"""

_TYPES = {
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


def load_rust_engine():
    import adblock

    (VENDOR / "lists").mkdir(parents=True, exist_ok=True)
    filters = adblock.FilterSet()
    for name, url in LISTS.items():
        path = VENDOR / "lists" / name
        if not path.exists():
            print(f"  downloading {url}")
            urllib.request.urlretrieve(url, path)
        filters.add_filter_list(path.read_text(encoding="utf-8"))
    return adblock.Engine(filters, optimize=True)


class Interceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, engine) -> None:
        super().__init__()
        self.engine = engine
        self.checked = 0
        self.blocked = 0

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:  # noqa: N802
        url = info.requestUrl().toString()
        if not url.startswith("http"):
            return
        self.checked += 1
        kind = _TYPES.get(info.resourceType(), "other")
        source = info.firstPartyUrl().toString() or url
        if self.engine.check_network_urls(url, source, kind).matched:
            self.blocked += 1
            info.block(True)


class Probe:
    def __init__(self, app: QApplication, mode: str, url: str, seconds: float) -> None:
        self.app, self.mode, self.url, self.seconds = app, mode, url, seconds
        storage = VENDOR / f"profile_{mode}"
        shutil.rmtree(storage, ignore_errors=True)  # fresh: consent and all
        self.profile = QWebEngineProfile(f"lf-adblock-{mode}")
        self.profile.setPersistentStoragePath(str(storage))
        self.profile.setCachePath(str(storage / "cache"))
        self.profile.settings().setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False
        )
        self.interceptor = None
        self.engine = None
        self.page = QWebEnginePage(self.profile)
        self.view = QWebEngineView()
        self.view.setPage(self.page)
        self.view.resize(1100, 700)
        self.view.setWindowTitle(f"Linguaflow adblock probe: {mode}")
        self.samples: list[dict] = []
        self.rejected = ""
        self.timer = QTimer()
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        self.started = 0.0

    def run(self) -> None:
        self.view.show()
        if self.mode == "ubol":
            manager = self.profile.extensionManager()
            manager.loadFinished.connect(self._extension_loaded)
            manager.installFinished.connect(self._extension_loaded)
            if "--load" in sys.argv:
                manager.loadExtension(str(UBOL))
            else:
                manager.installExtension(str(UBOL))
            return
        if self.mode == "yt":
            script = QWebEngineScript()
            script.setName("lf-youtube-ads")
            script.setSourceCode(YT_SCRIPTLET)
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            script.setRunsOnSubFrames(True)
            self.profile.scripts().insert(script)
        if self.mode in ("rust", "yt"):
            t = time.monotonic()
            self.engine = load_rust_engine()
            self.interceptor = Interceptor(self.engine)
            self.profile.setUrlRequestInterceptor(self.interceptor)
            print(f"  adblock-rust engine ready in {time.monotonic() - t:.1f} s")
            self.page.loadFinished.connect(self._inject_cosmetics)
        self._open()

    def _extension_loaded(self, info) -> None:
        print(f"  extension: name={info.name()!r} loaded={info.isLoaded()} "
              f"enabled={info.isEnabled()} error={info.error()!r}")
        if info.isLoaded() and not info.isEnabled() and "--enable" in sys.argv:
            QTimer.singleShot(0, self._enable_extensions)
        # uBOL fetches its rulesets on first start; give it a moment.
        QTimer.singleShot(3000, self._open)

    def _enable_extensions(self) -> None:
        manager = self.profile.extensionManager()
        for ext in manager.extensions():
            if not ext.isEnabled():
                manager.setExtensionEnabled(ext, True)
        print(f"  enabled: {[(e.name(), e.isEnabled()) for e in manager.extensions()]}", flush=True)

    def _open(self) -> None:
        print(f"  loading {self.url}")
        self.page.load(QUrl(self.url))
        self.started = time.monotonic()
        self.timer.start()

    def _inject_cosmetics(self, ok: bool) -> None:
        url = self.page.url().toString()
        res = self.engine.url_cosmetic_resources(url)
        css = ", ".join(res.hide_selectors)
        script = ""
        if css:
            script += (
                "(() => { const s = document.createElement('style');"
                f" s.textContent = {json.dumps(css + ' { display: none !important; }')};"
                " document.documentElement.appendChild(s); })();"
            )
        if res.injected_script:
            script += res.injected_script
        print(f"  cosmetics for {url[:50]}: {len(res.hide_selectors)} selectors, "
              f"script {len(res.injected_script)} chars")
        if script:
            self.page.runJavaScript(script, 0)

    def _tick(self) -> None:
        if not self.rejected:
            self.page.runJavaScript(REJECT_JS, 0, self._consent)
        self.page.runJavaScript(STATE_JS, 0, self._state)
        if time.monotonic() - self.started > self.seconds:
            self.timer.stop()
            self.view.grab().save(str(ROOT / "spike" / f"adblock_{self.mode}.png"))
            QTimer.singleShot(200, self.app.quit)

    def _consent(self, clicked: str) -> None:
        if clicked:
            self.rejected = clicked
            print(f"  consent: clicked «{clicked}»")

    def _state(self, result: str) -> None:
        if result:
            self.samples.append(json.loads(result))


def report(probe: Probe) -> None:
    samples = [s for s in probe.samples if s.get("playing")]
    ad = sum(1 for s in samples if s["ad"]) * 0.5
    main = sum(1 for s in samples if not s["ad"]) * 0.5
    print(f"\n== {probe.mode} ==")
    print(f"  playing {len(samples) * 0.5:.1f} s: ad {ad:.1f} s, video {main:.1f} s")
    if samples:
        print(f"  last: {samples[-1]}")
    if probe.interceptor:
        print(f"  requests checked {probe.interceptor.checked}, blocked {probe.interceptor.blocked}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("none", "ubol", "rust", "yt"))
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    parser.add_argument("--seconds", type=float, default=40.0)
    parser.add_argument("--load", action="store_true", help="ubol: loadExtension instead of install")
    parser.add_argument("--enable", action="store_true", help="ubol: call setExtensionEnabled")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    probe = Probe(app, args.mode, args.url, args.seconds)
    probe.run()
    app.exec()
    report(probe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
