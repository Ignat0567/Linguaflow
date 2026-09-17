"""Speaking translated text aloud, with Piper.

Measured on Day 0: a real-time factor of about 0.03 on CPU, so synthesis is
never the constraint. What is difficult is *fitting*: a translated sentence
rarely takes the same time to say as the original did. Russian runs longer than
English, German longer still, and a dub that ignores this drifts further out of
step with every line.

Piper can be asked to speak faster, which is the lever used here -- but not
proportionally: see LENGTH_RESPONSE below for what was measured. The practical
ceiling is 15-20% off a line, and past that a translation is allowed to run
over rather than be squeezed into a chipmunk.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import languages

#: Piper's own output rate for the medium voices used here.
NATIVE_RATE = 22_050

#: How far Piper's length_scale may be pushed to make a line fit.
#:
#: Below about 0.72 the voice stops sounding like a person. A line that still
#: does not fit is allowed to run over rather than be squeezed further -- an
#: overlap of a few hundred milliseconds is far less noticeable than a
#: chipmunk. It is never stretched to fill silence either: a dub that drawls
#: sounds worse than one that finishes early.
MIN_LENGTH_SCALE, MAX_LENGTH_SCALE = 0.72, 1.0

#: How much of a change in length_scale actually reaches the duration.
#:
#: Not 1.0, which is the obvious assumption and is wrong. Measured on
#: ru_RU-dmitri-medium: length_scale 0.909 shortened a 3.32 s line by 1%, not
#: the 9% asked for, and 0.770 shortened it by 13%, not 23%. Part of every
#: utterance -- leading and trailing silence, and the model's own floor on
#: phoneme length -- does not scale at all.
#:
#: The practical consequence is a ceiling: Piper can take roughly 15-20% off a
#: line before it stops sounding human, so a translation much longer than its
#: original will overrun however it is asked.
LENGTH_RESPONSE = 0.55


class VoiceError(RuntimeError):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


@dataclass(frozen=True)
class Utterance:
    """One spoken line, with the timing it was asked to fill."""

    samples: np.ndarray
    rate: int
    start: float
    #: The slot it was asked to fit.
    wanted: float
    #: Piper's length scale used; below 1.0 means the line was compressed.
    length_scale: float

    @property
    def duration(self) -> float:
        return len(self.samples) / self.rate

    @property
    def overran(self) -> bool:
        return self.duration > self.wanted + 0.05

    @property
    def compressed(self) -> bool:
        return self.length_scale < 0.999


class Speaker:
    """A loaded Piper voice.

    Loading costs a moment and a little memory, so one instance is meant to be
    kept for the length of a job rather than created per line.
    """

    def __init__(self, language: str, voice: str | None = None,
                 voices_dir: Path | str | None = None) -> None:
        self.language = language
        self.voice_name = voice or self._default_voice(language)
        self.voices_dir = Path(voices_dir or Path.cwd() / "models" / "piper")
        self._voice = self._load()

    @staticmethod
    def _default_voice(language: str) -> str:
        entry = languages.get(language)
        if entry is None or not entry.piper_voice:
            raise VoiceError(
                f"Для языка «{languages.describe(language)}» не задан голос."
            )
        return entry.piper_voice

    def _load(self):
        from piper import PiperVoice

        path = self.voices_dir / f"{self.voice_name}.onnx"
        if not path.exists():
            raise VoiceError(
                f"Голос «{self.voice_name}» не скачан. Загрузите его командой:\n"
                f"  python -m piper.download_voices --data-dir {self.voices_dir} "
                f"{self.voice_name}"
            )
        try:
            return PiperVoice.load(str(path.resolve()))
        except Exception as exc:
            raise VoiceError(
                f"Не удалось загрузить голос «{self.voice_name}».", str(exc)
            ) from exc

    # -- synthesis -------------------------------------------------------
    def say(self, text: str, length_scale: float = 1.0) -> tuple[np.ndarray, int]:
        """Speak `text`; return float32 samples and their rate.

        `length_scale` below 1.0 is faster, which is Piper's own convention.
        """
        text = text.strip()
        if not text:
            return np.zeros(0, dtype=np.float32), NATIVE_RATE

        from piper import SynthesisConfig

        config = SynthesisConfig(length_scale=length_scale)
        try:
            chunks = list(self._voice.synthesize(text, syn_config=config))
        except Exception as exc:
            raise VoiceError("Синтез речи не удался.", str(exc)) from exc
        if not chunks:
            return np.zeros(0, dtype=np.float32), NATIVE_RATE

        rate = chunks[0].sample_rate
        raw = b"".join(chunk.audio_int16_bytes for chunk in chunks)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return samples, rate

    def fit(self, text: str, start: float, seconds: float) -> Utterance:
        """Speak `text` so that it fits `seconds`, as far as that is sensible.

        Synthesised once at normal speed to find out how long the line actually
        takes, then re-synthesised at the speed that would fit it. Estimating
        from character counts instead is tempting and wrong: the ratio varies
        with the sentence, and being wrong here means either a rushed line or a
        gap.
        """
        samples, rate = self.say(text)
        if samples.size == 0 or seconds <= 0:
            return Utterance(samples, rate, start, seconds, 1.0)

        natural = len(samples) / rate
        if natural <= seconds * 1.02:
            return Utterance(samples, rate, start, seconds, 1.0)

        # Ask for the scale that LENGTH_RESPONSE says will land on the slot,
        # rather than the ratio itself -- which under-corrects by roughly half.
        wanted_ratio = seconds / natural
        scale = 1.0 + (wanted_ratio - 1.0) / LENGTH_RESPONSE
        scale = max(MIN_LENGTH_SCALE, min(MAX_LENGTH_SCALE, scale))

        samples, rate = self.say(text, length_scale=scale)
        return Utterance(samples, rate, start, seconds, scale)


def resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or samples.size == 0:
        return samples
    import soxr

    return soxr.resample(samples, source_rate, target_rate, quality="VHQ").astype(
        np.float32, copy=False
    )


def write_wav(path: Path | str, samples: np.ndarray, rate: int) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        peaks = np.clip(samples, -1.0, 1.0)
        wav.writeframes((peaks * 32767).astype(np.int16).tobytes())
    return target
