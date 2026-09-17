"""Getting audio out of whatever the user points at.

A local file, or a URL that yt-dlp can resolve. Both end up as a path that
ffmpeg can decode, because everything downstream only wants samples.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_URL = re.compile(r"^https?://", re.IGNORECASE)


class MediaError(RuntimeError):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    duration: float
    title: str
    has_audio: bool
    #: Whether there is a picture to put a new soundtrack against. A dubbed
    #: copy is only possible when there is.
    has_video: bool = False
    source_url: str | None = None


def is_url(target: str) -> bool:
    return bool(_URL.match(target.strip()))


def _ffprobe_exe() -> str:
    """ffprobe sits beside the ffmpeg binary imageio-ffmpeg ships.

    Except when it does not: some wheels carry only ffmpeg. Callers fall back
    to ffmpeg's own output in that case.
    """
    from .audio.dshow import ffmpeg_path

    ffmpeg = Path(ffmpeg_path())
    candidate = ffmpeg.with_name(ffmpeg.name.replace("ffmpeg", "ffprobe"))
    return str(candidate) if candidate.exists() else ""


def probe(path: Path | str) -> MediaInfo:
    """Read duration and stream layout without decoding the whole file."""
    target = Path(path).resolve()
    if not target.exists():
        raise MediaError(f"Файл не найден: {target}")

    probe_exe = _ffprobe_exe()
    if probe_exe:
        try:
            completed = subprocess.run(
                [probe_exe, "-v", "error", "-print_format", "json",
                 "-show_format", "-show_streams", str(target)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60, creationflags=_NO_WINDOW,
            )
            if completed.returncode == 0:
                payload = json.loads(completed.stdout)
                streams = payload.get("streams", [])
                return MediaInfo(
                    path=target,
                    duration=float(payload.get("format", {}).get("duration", 0.0)),
                    title=target.stem,
                    has_audio=any(s.get("codec_type") == "audio" for s in streams),
                    # A cover image inside an MP3 is a video stream by
                    # ffprobe's reckoning. One still frame is not a video, and
                    # muxing a soundtrack against it would produce a file that
                    # claims to be one.
                    has_video=any(
                        s.get("codec_type") == "video"
                        and s.get("disposition", {}).get("attached_pic", 0) != 1
                        and (s.get("nb_frames") is None
                             or int(s.get("nb_frames") or 0) > 1)
                        for s in streams
                    ),
                )
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            pass

    return _probe_with_ffmpeg(target)


def _probe_with_ffmpeg(target: Path) -> MediaInfo:
    """Fallback: read what ffmpeg prints when asked to open the file.

    ffmpeg exits non-zero here because no output was requested. That is
    expected and says nothing about whether the file is readable.
    """
    from .audio.dshow import ffmpeg_path

    completed = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(target)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, creationflags=_NO_WINDOW,
    )
    output = completed.stderr

    duration = 0.0
    matched = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2})\.(\d+)", output)
    if matched:
        hours, minutes, seconds, fraction = matched.groups()
        duration = (int(hours) * 3600 + int(minutes) * 60 + int(seconds)
                    + float(f"0.{fraction}"))
    has_audio = bool(re.search(r"Stream #\d+:\d+.*: Audio:", output))
    has_video = bool(re.search(r"Stream #\d+:\d+.*: Video:", output)) and not bool(
        re.search(r"Video:.*\(attached pic\)", output)
    )

    if duration == 0.0 and not has_audio:
        raise MediaError(
            f"Не удалось прочитать «{target.name}» — формат не распознан.",
            detail=output.strip()[-500:],
        )
    return MediaInfo(path=target, duration=duration, title=target.stem,
                     has_audio=has_audio, has_video=has_video)


def fetch_url(
    url: str,
    into: Path | str,
    timeout: float = 1800.0,
    want_video: bool = False,
) -> MediaInfo:
    """Download a URL with yt-dlp.

    Audio only by default: the video is downloaded and discarded otherwise,
    which on a long recording is gigabytes of traffic for nothing. Asked for
    a dubbed copy of the picture, there is no way around fetching it, so
    `want_video` says so explicitly rather than guessing.
    """
    try:
        import yt_dlp  # noqa: F401
    except ImportError as exc:
        raise MediaError(
            "Поддержка ссылок требует yt-dlp: pip install yt-dlp"
        ) from exc

    destination = Path(into).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    if want_video:
        wanted = [
            "--format", "bestvideo*+bestaudio/best",
            "--merge-output-format", "mp4",
        ]
    else:
        wanted = [
            "--format", "bestaudio/best",
            "--extract-audio", "--audio-format", "wav",
        ]
    command = [
        str(Path(_python_exe())), "-m", "yt_dlp",
        "--no-playlist", "--no-warnings", "--quiet",
        *wanted,
        "--print", "after_move:filepath",
        "--output", str(destination / "%(title).120B.%(ext)s"),
        url,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"Скачивание превысило {timeout / 60:.0f} мин.") from exc

    if completed.returncode != 0:
        raise MediaError(
            "Не удалось скачать по ссылке. Проверьте адрес и доступность "
            "видео (приватные и возрастные записи требуют входа).",
            detail=(completed.stderr or completed.stdout).strip()[-500:],
        )

    downloaded = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not downloaded:
        raise MediaError("yt-dlp не сообщил, куда сохранил файл.",
                         detail=completed.stdout[-500:])

    info = probe(Path(downloaded[-1]))
    return MediaInfo(path=info.path, duration=info.duration, title=info.path.stem,
                     has_audio=info.has_audio, has_video=info.has_video,
                     source_url=url)


def _python_exe() -> str:
    import sys

    # Store-Python virtualises paths given to subprocesses; resolve first.
    return str(Path(sys.executable).resolve())


def resolve(
    target: str, download_dir: Path | str, want_video: bool = False
) -> MediaInfo:
    """Accept a path or a URL and return something decodable either way."""
    if is_url(target):
        return fetch_url(target, download_dir, want_video=want_video)
    return probe(target)
