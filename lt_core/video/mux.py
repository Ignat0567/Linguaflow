"""A copy of the video with the translated soundtrack against the picture.

Nothing is re-encoded except the audio. The picture is copied stream to
stream, so a twenty-minute film takes seconds rather than an hour and comes
out bit-identical to the original -- re-encoding it would cost quality for a
change that does not touch a single frame.

The original soundtrack is kept as a second track rather than thrown away.
A player offers both, the translated one first; anyone who wants to check a
line against what was actually said can switch to it without going back to
the source file. The translated subtitles go in as a third track, for the
same reason and at the same cost, which is none.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import languages
from ..audio.dshow import ffmpeg_path

#: Containers that can hold what we put in them. Anything else is written as
#: MP4, which every player on the user's machine already opens.
NATIVE_CONTAINERS = {".mp4", ".mkv", ".mov", ".webm"}

#: MP4 keeps subtitles as `mov_text`; Matroska and WebM keep SubRip as-is.
SUBTITLE_CODEC = {
    ".mp4": "mov_text", ".mov": "mov_text", ".mkv": "srt", ".webm": "webvtt",
}

#: Windows: do not flash a console window for a background ffmpeg.
_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class MuxError(RuntimeError):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


@dataclass
class MuxResult:
    path: Path
    #: Whether the original soundtrack rode along as a second track.
    kept_original: bool
    #: Whether the translated subtitles rode along as a third.
    with_subtitles: bool
    seconds: float = 0.0
    #: The length the copy was cut to, which is the picture's own.
    duration: float = 0.0

    @property
    def size_mb(self) -> float:
        return self.path.stat().st_size / (1024 * 1024) if self.path.exists() else 0.0


def container_for(source: Path) -> str:
    suffix = source.suffix.lower()
    return suffix if suffix in NATIVE_CONTAINERS else ".mp4"


def replace_audio(
    video: Path | str,
    dub: Path | str,
    destination: Path | str,
    target_language: str = "",
    source_language: str = "",
    subtitles: Path | str | None = None,
    keep_original: bool = True,
    duration: float = 0.0,
    timeout: float = 3600.0,
) -> MuxResult:
    """Write a copy of `video` whose first soundtrack is `dub`."""
    import time

    source = Path(video).resolve()
    voice = Path(dub).resolve()
    if not source.exists():
        raise MuxError(f"Видео не найдено: {source}")
    if not voice.exists():
        raise MuxError(f"Звуковая дорожка не найдена: {voice}")

    out = Path(destination)
    if out.suffix.lower() not in NATIVE_CONTAINERS:
        out = out.with_suffix(container_for(source))
    out.parent.mkdir(parents=True, exist_ok=True)

    subtitle_path = Path(subtitles).resolve() if subtitles else None
    if subtitle_path is not None and not subtitle_path.exists():
        subtitle_path = None

    command: list[str] = [
        ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source), "-i", str(voice),
    ]
    if subtitle_path is not None:
        command += ["-i", str(subtitle_path)]

    # The picture from the source, the translated voice first, then the
    # original. `0:a:0?` is optional on purpose: a silent film has no
    # soundtrack to carry over and that is not an error.
    command += ["-map", "0:v:0", "-map", "1:a:0"]
    if keep_original:
        command += ["-map", "0:a:0?"]
    if subtitle_path is not None:
        command += ["-map", f"{2}:s:0"]

    command += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    if subtitle_path is not None:
        command += ["-c:s", SUBTITLE_CODEC.get(out.suffix.lower(), "mov_text")]

    # Track names: a player shows these in its audio menu, and without them
    # two entries both called "Audio" are a guess.
    command += [
        "-metadata:s:a:0",
        f"title=Перевод ({languages.describe(target_language) or 'перевод'})",
        "-metadata:s:a:0", f"language={languages.track_language(target_language)}",
        "-disposition:a:0", "default",
    ]
    if keep_original:
        command += [
            "-metadata:s:a:1",
            f"title=Оригинал ({languages.describe(source_language) or 'исходный'})",
            "-metadata:s:a:1",
            f"language={languages.track_language(source_language)}",
            "-disposition:a:1", "0",
        ]
    if subtitle_path is not None:
        command += [
            "-metadata:s:s:0", f"language={languages.track_language(target_language)}"
        ]

    # The picture decides how long the copy is, and it is asked directly.
    #
    # `-shortest` is the obvious way to say this and is wrong here: it ends
    # the output when any input stream ends, and the subtitle track ends at
    # the last caption. Measured -- a 105.7 s video whose last caption closed
    # at 103.7 s came out 103.7 s long, two seconds of picture dropped, purely
    # because subtitles had been added. Nobody debugging a truncated video
    # would look for the cause in the subtitle track.
    if duration <= 0.0:
        from ..media import probe

        try:
            duration = probe(source).duration
        except Exception:  # noqa: BLE001 -- an unreadable length is not fatal
            duration = 0.0
    if duration > 0.0:
        command += ["-t", f"{duration:.3f}"]
    command.append(str(out))

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise MuxError(
            f"Сборка видео превысила {timeout / 60:.0f} мин."
        ) from exc
    except OSError as exc:
        raise MuxError("Не удалось запустить ffmpeg.", str(exc)) from exc

    if completed.returncode != 0 or not out.exists():
        raise MuxError(
            f"Не удалось собрать «{out.name}».",
            detail=(completed.stderr or completed.stdout).strip()[-600:],
        )

    return MuxResult(
        path=out,
        kept_original=keep_original,
        with_subtitles=subtitle_path is not None,
        seconds=time.perf_counter() - started,
        duration=duration,
    )
