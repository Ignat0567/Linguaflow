"""Writing transcripts out.

SRT and WebVTT for subtitles, plain text for reading, JSON for anything that
needs the timings back.

Both subtitle formats are written UTF-8 without a BOM. A BOM is tempting on
Windows -- some players want it -- but ffmpeg and most web players treat those
three bytes as part of the first cue number and refuse the file. UTF-8 plain is
the interoperable choice.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..asr.types import Transcript
from .cues import Cue


def format_srt_time(seconds: float) -> str:
    """HH:MM:SS,mmm -- SRT uses a comma for the decimal separator."""
    seconds = max(0.0, seconds)
    milliseconds = int(round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{milliseconds:03d}"


def format_vtt_time(seconds: float) -> str:
    """HH:MM:SS.mmm -- WebVTT uses a period, and rejects a comma."""
    return format_srt_time(seconds).replace(",", ".")


def to_srt(cues: tuple[Cue, ...]) -> str:
    blocks = [
        f"{position}\n"
        f"{format_srt_time(cue.start)} --> {format_srt_time(cue.end)}\n"
        f"{cue.text}"
        for position, cue in enumerate(cues, start=1)
    ]
    return "\n\n".join(blocks) + "\n"


def to_vtt(cues: tuple[Cue, ...]) -> str:
    blocks = [
        f"{format_vtt_time(cue.start)} --> {format_vtt_time(cue.end)}\n{cue.text}"
        for cue in cues
    ]
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


def to_text(transcript: Transcript, timestamps: bool = False) -> str:
    """Readable prose rather than subtitles.

    Segment boundaries become paragraph breaks: they follow the speaker's
    pauses, which is closer to how the speech was actually delivered than any
    re-flowing would be.
    """
    if not timestamps:
        return "\n".join(
            segment.text.strip() for segment in transcript.segments
        ).strip() + "\n"

    lines = []
    for segment in transcript.segments:
        stamp = format_srt_time(segment.start)[:-4]  # HH:MM:SS
        lines.append(f"[{stamp}] {segment.text.strip()}")
    return "\n".join(lines) + "\n"


def to_json(transcript: Transcript, cues: tuple[Cue, ...] | None = None) -> str:
    payload = {
        "language": transcript.language,
        "language_probability": round(transcript.language_probability, 4),
        "duration": round(transcript.duration, 3),
        "model": transcript.model,
        "elapsed": round(transcript.elapsed, 3),
        "realtime_factor": round(transcript.realtime_factor, 4),
        "segments": [
            {
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "text": segment.text.strip(),
                "avg_logprob": round(segment.avg_logprob, 4),
                "words": [
                    {
                        "text": word.text.strip(),
                        "start": round(word.start, 3),
                        "end": round(word.end, 3),
                        "probability": round(word.probability, 4),
                    }
                    for word in segment.words
                ],
            }
            for segment in transcript.segments
        ],
    }
    if cues is not None:
        payload["cues"] = [
            {
                "index": cue.index,
                "start": round(cue.start, 3),
                "end": round(cue.end, 3),
                "lines": list(cue.lines),
            }
            for cue in cues
        ]
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def write(path: Path | str, content: str) -> Path:
    """Write UTF-8 without a BOM, with Unix line endings.

    SRT files travel between players and operating systems; CRLF is tolerated
    everywhere but produces stray characters in some parsers, LF does not.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")
    return target


EXPORTERS = {
    "srt": lambda transcript, cues: to_srt(cues),
    "vtt": lambda transcript, cues: to_vtt(cues),
    "txt": lambda transcript, cues: to_text(transcript),
    "tsv": lambda transcript, cues: to_text(transcript, timestamps=True),
    "json": lambda transcript, cues: to_json(transcript, cues),
}
