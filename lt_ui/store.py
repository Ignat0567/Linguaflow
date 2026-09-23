"""Settings and history that survive a restart.

The handoff's prototype kept this in component state and reset it on every
reload. A real session that took twelve minutes to transcribe is worth
finding again tomorrow, and the language pair a user set should still be
the language pair when they open the app.

Nothing here talks to a server. Settings, history and keys live in the
per-user folder; the models stay with the installation.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from lt_core import languages
from lt_core.install import install_root, model_root
from lt_core.mt.types import TranslationMode

from .i18n import UI_LANGUAGES
from .keys import KeyStore
from .paths import default_output_dir, resolve_data_dir

ROOT = install_root()
#: Gigabytes, identical for every user, read-only in use: they stay with the
#: installation rather than being copied into each profile.
MODEL_ROOT = model_root()

SCREENS = ("home", "realtime", "browser", "upload", "history", "settings")

_MONTHS = {
    "ru": (
        "янв", "фев", "мар", "апр", "мая", "июн",
        "июл", "авг", "сент", "окт", "ноя", "дек",
    ),
    "en": (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sept", "Oct", "Nov", "Dec",
    ),
    "de": (
        "Jan.", "Feb.", "März", "Apr.", "Mai", "Juni",
        "Juli", "Aug.", "Sept.", "Okt.", "Nov.", "Dez.",
    ),
}


def display_name(code: str) -> str:
    """The language's name, capitalised, in whatever the interface speaks.

    Goes through the interface catalogue rather than the core registry: the
    registry names every language in Russian, which is right for a log and
    wrong for a picker in a German window.
    """
    from .i18n import language_name

    name = language_name(code)
    return name[:1].upper() + name[1:] if name else code


def format_clock(seconds: float) -> str:
    total = int(round(max(0.0, seconds)))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def format_date(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    from . import i18n

    months = _MONTHS.get(i18n.LANGUAGE, _MONTHS["ru"])
    month = months[moment.month - 1]
    if i18n.LANGUAGE == "de":
        return f"{moment.day}. {month} {moment.year}"
    return f"{moment.day} {month} {moment.year}"


def split_terms(text: str) -> tuple[str, ...]:
    """The words a user typed, however they chose to separate them.

    Commas, semicolons and new lines all mean the same thing to somebody
    typing a handful of names into a box, and a list that only works one way
    is a list that silently does nothing half the time.
    """
    import re

    parts = re.split(r"[,;\n\r\t]+", text or "")
    return tuple(dict.fromkeys(
        part.strip() for part in parts if part and part.strip()
    ))


@dataclass
class Settings:
    from_lang: str = "ru"
    to_lang: str = "en"
    #: File mode only. When true, Whisper identifies the source language
    #: instead of using `from_lang`. Live mode still needs an explicit pair.
    detect_language: bool = True
    #: Words this recording uses that the recogniser will not guess: names,
    #: jargon, a product nobody has heard of. Comma-separated, as typed.
    terms: str = ""
    #: What kind of live session: one speaker, or two who share no language.
    realtime_mode: str = "subtitles"  # subtitles | conversation
    #: Read the translation out loud as well as showing it. Orthogonal to the
    #: mode -- a conversation is where hearing it matters most, and it used to
    #: be the one place it could not be turned on, because "Текст + озвучка"
    #: was a third value of the mode itself.
    realtime_voice: bool = False
    voiceover: bool = True
    #: Read a man in a male voice and a woman in a female one, deciding per
    #: line from the pitch of the original.
    match_voices: bool = True
    #: For a video source, also write a copy of it with the translated
    #: soundtrack against the picture.
    dub_video: bool = True
    #: Trim filler out of a translated line when it cannot be spoken in the
    #: time the original took.
    condense: bool = True
    #: Which service rewrites the lines the rules could not shorten. Empty
    #: means rules only, and nothing leaves the machine. Its key is read from
    #: the service's environment variable rather than stored here: a settings
    #: file is not a place to keep someone's API key.
    shorten_with: str = ""
    sub_format: str = "srt"
    notify: bool = True
    translation_mode: str = TranslationMode.OFFLINE
    online_service: str = "deepl"
    capture_kind: str = "microphone"  # microphone | system
    accent: str = "#7fa4ff"
    #: "dark" or "light". The handoff is dark; the light theme is a second set
    #: of values rather than an inversion of it.
    appearance: str = "dark"
    #: Which language the interface itself speaks: ru, en or de.
    ui_language: str = "ru"
    #: Where finished files are written. Empty means the default -- a folder
    #: called «translated» beside the user's other videos -- and is stored
    #: empty rather than resolved, so that a profile copied to another
    #: machine, or a Videos folder moved to another drive, still lands in the
    #: right place. A folder chosen by the user is used as given: someone who
    #: picks «Загрузки» wants the file in «Загрузки», not in a subfolder.
    output_dir: str = ""
    #: Where the browser screen was last. Empty means its home page.
    browser_url: str = ""
    #: Pause the browser's video when the translation read aloud falls too
    #: far behind it (lt_ui.browser.CatchUp). Off by default: the voice no
    #: longer costs recognition anything (it reads on its own thread), and a
    #: video that stops for ten seconds at a time reads as a fault.
    browser_catch_up: bool = False
    #: The language of the videos watched in the browser; "auto" detects it.
    #: Separate from the Live screen's, which is a person's own language.
    browser_from_lang: str = "auto"
    #: What the browser translates into. Its own, too: sharing the Live
    #: screen's meant a Russian speaker's «ru -> en» there made the browser
    #: translate every video into English -- and a browser «-> ru» beside the
    #: Live screen's «ru ->» was "clamped" back to English on every save.
    browser_to_lang: str = "ru"
    #: Floating caption window over the meeting.
    overlay: bool = True
    #: True: the window stays on this monitor but is absent from Zoom/Meet
    #: full-screen capture. False: it is shared along with the desktop.
    overlay_hidden_from_share: bool = True
    overlay_x: int = -1
    overlay_y: int = -1
    overlay_w: int = 720
    overlay_h: int = 168

    def offered(self) -> tuple[str, ...]:
        return tuple(languages.active())

    def clamp(self) -> None:
        """Drop values that this build cannot honour.

        A settings file from a wider language set, or a typo, should not
        leave the pickers pointing at a language nobody can select.
        """
        offered = self.offered() or ("ru", "en")
        if self.from_lang not in offered:
            self.from_lang = offered[0]
        if self.to_lang not in offered or self.to_lang == self.from_lang:
            self.to_lang = next(
                (code for code in offered if code != self.from_lang), offered[0]
            )
        if self.browser_to_lang not in offered:
            self.browser_to_lang = "ru" if "ru" in offered else offered[0]
        if (self.browser_from_lang not in (*offered, "auto")
                or self.browser_from_lang == self.browser_to_lang):
            self.browser_from_lang = "auto"
        if self.realtime_mode == "voice":
            # It was a mode before it was an option; carry the choice across.
            self.realtime_mode, self.realtime_voice = "subtitles", True
        if self.realtime_mode not in {"subtitles", "conversation"}:
            self.realtime_mode = "subtitles"
        if self.sub_format not in {"srt", "vtt", "txt"}:
            self.sub_format = "srt"
        if self.translation_mode not in {
            TranslationMode.OFFLINE, TranslationMode.ONLINE
        }:
            self.translation_mode = TranslationMode.OFFLINE
        if self.capture_kind not in {"microphone", "system"}:
            self.capture_kind = "microphone"
        if self.shorten_with not in {"", "groq", "openai", "nvidia", "local"}:
            self.shorten_with = ""
        if self.appearance not in {"dark", "light"}:
            self.appearance = "dark"
        if self.ui_language not in UI_LANGUAGES:
            self.ui_language = "ru"
        self.overlay_w = max(420, int(self.overlay_w))
        self.overlay_h = max(128, int(self.overlay_h))
        # A folder on a drive that has since been unplugged must not stop a
        # job halfway through writing to it.
        if self.output_dir and not Path(self.output_dir).is_dir():
            self.output_dir = ""


    def set_from(self, code: str) -> None:
        if code == self.to_lang:
            self.to_lang = self.from_lang
        self.from_lang = code
        self.clamp()

    def set_to(self, code: str) -> None:
        if code == self.from_lang:
            self.from_lang = self.to_lang
        self.to_lang = code
        self.clamp()

    def swap(self) -> None:
        self.from_lang, self.to_lang = self.to_lang, self.from_lang


@dataclass
class HistoryEntry:
    id: str
    kind: str  # live | file
    title: str
    source_language: str
    target_language: str
    duration: float
    created: str
    folder: str = ""
    outputs: dict[str, str] = field(default_factory=dict)

    @property
    def is_live(self) -> bool:
        return self.kind == "live"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "HistoryEntry":
        known = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in payload.items() if key in known})


def new_id() -> str:
    return uuid.uuid4().hex[:10]


class Store:
    """One JSON file for settings, one for the history list."""

    def __init__(self, root: Path | str | None = None) -> None:
        # Per-user, and migrated out of the old `data/` beside the code the
        # first time. See lt_ui.paths for why.
        self.root = resolve_data_dir(ROOT, root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = Settings()
        self.entries: list[HistoryEntry] = []
        #: Kept apart from the settings, and encrypted per user where the
        #: platform allows it. See lt_ui.keys.
        self.keys = KeyStore(self.root)
        self.load()

    @property
    def settings_path(self) -> Path:
        return self.root / "settings.json"

    @property
    def history_path(self) -> Path:
        return self.root / "history.json"

    @property
    def jobs(self) -> Path:
        path = self.root / "jobs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load(self) -> None:
        if self.settings_path.exists():
            try:
                payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            known = {item.name for item in fields(Settings)}
            self.settings = Settings(
                **{key: value for key, value in payload.items() if key in known}
            )
        self.settings.clamp()

        if self.history_path.exists():
            try:
                rows = json.loads(self.history_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                rows = []
            self.entries = [
                HistoryEntry.from_dict(row) for row in rows if isinstance(row, dict)
            ]

    def save_settings(self) -> None:
        self.settings.clamp()
        self.settings_path.write_text(
            json.dumps(asdict(self.settings), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def save_history(self) -> None:
        self.history_path.write_text(
            json.dumps(
                [entry.to_dict() for entry in self.entries],
                ensure_ascii=False, indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    def add(self, entry: HistoryEntry) -> HistoryEntry:
        self.entries.insert(0, entry)
        self.save_history()
        return entry

    def clear_history(self) -> int:
        """Forget the list of past jobs; the files themselves are untouched.

        Deliberately: the entries name folders the user may still want, and a
        button in a list is not where someone expects gigabytes to be deleted
        from disk.
        """
        removed = len(self.entries)
        self.entries = []
        self.save_history()
        return removed

    def recent(self, limit: int = 3) -> list[HistoryEntry]:
        return self.entries[:limit]

    def job_dir(self, entry_id: str) -> Path:
        """Where this job's files go: the chosen folder, or the default one.

        The default is «translated» beside the user's videos. Inside the
        application's own data would be tidier and wrong: these are the files
        the work was done for, and they belong where a person keeps such
        files, not in a folder they would have to be told about.
        """
        for candidate in (self.settings.output_dir, default_output_dir()):
            if not candidate:
                continue
            path = Path(candidate)
            try:
                path.mkdir(parents=True, exist_ok=True)
                return path
            except OSError:
                # Read-only, or on a drive that is no longer there. Forget a
                # chosen folder so the next job does not retry it, and fall
                # through to somewhere that will certainly work.
                if candidate == self.settings.output_dir:
                    self.settings.output_dir = ""
                    self.save_settings()
        path = self.jobs / entry_id
        path.mkdir(parents=True, exist_ok=True)
        return path
