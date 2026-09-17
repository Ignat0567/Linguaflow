"""Settings and history that survive a restart.

The handoff's prototype kept this in component state and reset it on every
reload. A real session that took twelve minutes to transcribe is worth
finding again tomorrow, and the language pair a user set should still be
the language pair when they open the app.

Nothing here talks to a server. The files live next to the models, in
`data/`, so a copy of the project carries its own memory.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from lt_core import languages
from lt_core.mt.types import TranslationMode

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data"
MODEL_ROOT = ROOT / "models"

SCREENS = ("home", "realtime", "upload", "history", "settings")

_MONTHS = (
    "янв", "фев", "мар", "апр", "мая", "июн",
    "июл", "авг", "сент", "окт", "ноя", "дек",
)


def display_name(code: str) -> str:
    """Capitalised name for pickers: «Русский», not «русский»."""
    name = languages.describe(code)
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
    return f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year}"


@dataclass
class Settings:
    from_lang: str = "ru"
    to_lang: str = "en"
    #: File mode only. When true, Whisper identifies the source language
    #: instead of using `from_lang`. Live mode still needs an explicit pair.
    detect_language: bool = True
    realtime_mode: str = "subtitles"  # subtitles | voice | conversation
    voiceover: bool = True
    #: Read a man in a male voice and a woman in a female one, deciding per
    #: line from the pitch of the original.
    match_voices: bool = True
    #: For a video source, also write a copy of it with the translated
    #: soundtrack against the picture.
    dub_video: bool = True
    sub_format: str = "srt"
    notify: bool = True
    translation_mode: str = TranslationMode.OFFLINE
    online_service: str = "deepl"
    capture_kind: str = "microphone"  # microphone | system
    accent: str = "#7fa4ff"
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
        if self.realtime_mode not in {"subtitles", "voice", "conversation"}:
            self.realtime_mode = "subtitles"
        if self.sub_format not in {"srt", "vtt", "txt"}:
            self.sub_format = "srt"
        if self.translation_mode not in {
            TranslationMode.OFFLINE, TranslationMode.ONLINE
        }:
            self.translation_mode = TranslationMode.OFFLINE
        if self.capture_kind not in {"microphone", "system"}:
            self.capture_kind = "microphone"
        self.overlay_w = max(420, int(self.overlay_w))
        self.overlay_h = max(128, int(self.overlay_h))

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
        self.root = Path(root) if root else DEFAULT_DATA
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = Settings()
        self.entries: list[HistoryEntry] = []
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

    def recent(self, limit: int = 3) -> list[HistoryEntry]:
        return self.entries[:limit]

    def job_dir(self, entry_id: str) -> Path:
        path = self.jobs / entry_id
        path.mkdir(parents=True, exist_ok=True)
        return path
