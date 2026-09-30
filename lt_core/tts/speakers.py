"""Telling the people in a recording apart by the sound of their voice.

Pitch alone cannot do it when a man and a woman share a register. Measured on
a 66-minute interview, a man and a woman: his lines sat at 90-130 Hz and ran
up to 150-190 when he was animated, which is exactly where hers were, so there
was no empty band to cut at and `casting` rightly read it all with one voice.

A voice print does not move with animation. Each line is turned into a
speaker embedding (wespeaker ResNet34, trained on VoxCeleb, run through
sherpa-onnx), the embeddings are clustered, and each cluster -- a person --
is then given a register from the median pitch of all their lines together,
which is steady where a single line is not. On the interview: 1110 lines at
109 Hz, 251 at 159 Hz holding every question the host asked, and a third
group of his «um»s.
"""

from __future__ import annotations

import urllib.request
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import numpy as np

MODEL_NAME = "wespeaker_en_voxceleb_resnet34_LM.onnx"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/" + MODEL_NAME
)
#: Bytes the model file has. A partial download is not a model.
MODEL_SIZE = 26_530_550

#: Shorter than this, a line carries too little voice to be recognised.
MIN_SECONDS = 1.0
#: Cosine distance at which two lines are taken to be different people.
#: On the interview 0.6 and 0.7 gave the same people; lower split one man
#: into many, which does no harm to the casting, merging a woman into a man
#: would.
THRESHOLD = 0.6
#: A group this small next to the others is a scrap of someone already
#: found (a laugh, a cough, crosstalk), and goes to the nearest real person.
MIN_SHARE = 0.03
MIN_LINES = 4


def model_path(model_dir: Path | str) -> Path:
    return Path(model_dir) / MODEL_NAME


def ensure_model(model_dir: Path | str) -> Path:
    """The model file, fetched on first use (26.5 MB)."""
    target = model_path(model_dir)
    if target.exists() and target.stat().st_size == MODEL_SIZE:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    with urllib.request.urlopen(MODEL_URL, timeout=60) as response, open(partial, "wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    if partial.stat().st_size != MODEL_SIZE:
        partial.unlink(missing_ok=True)
        raise OSError(f"{MODEL_NAME}: the download was cut short")
    partial.replace(target)
    return target


def identify(
    spans: Sequence, audio: np.ndarray, rate: int, model: Path | str,
    threads: int = 4,
) -> list[int | None]:
    """A speaker number for each span (anything with .start and .end).

    `None` for a span too short to recognise; `speaker_of` gives those
    their neighbours' speaker.
    """
    import sherpa_onnx

    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model), num_threads=threads)
    )
    prints: list[np.ndarray] = []
    measured: list[int] = []
    for index, span in enumerate(spans):
        if span.end - span.start < MIN_SECONDS:
            continue
        piece = audio[max(0, int(span.start * rate)):int(span.end * rate)]
        stream = extractor.create_stream()
        stream.accept_waveform(rate, np.ascontiguousarray(piece, dtype=np.float32))
        stream.input_finished()
        if not extractor.is_ready(stream):
            continue
        vector = np.asarray(extractor.compute(stream), dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            continue
        prints.append(vector / norm)
        measured.append(index)

    labels: list[int | None] = [None] * len(spans)
    if not prints:
        return labels
    if len(prints) == 1:
        labels[measured[0]] = 0
        return labels

    matrix = np.stack(prints)
    found = sherpa_onnx.FastClustering(
        sherpa_onnx.FastClusteringConfig(threshold=THRESHOLD)
    )(matrix)
    found = _absorb_scraps(np.asarray(found), matrix)
    for index, label in zip(measured, found):
        labels[index] = int(label)
    return labels


def _absorb_scraps(labels: np.ndarray, prints: np.ndarray) -> np.ndarray:
    """Give the lines of a too-small group to the nearest real person."""
    counts = Counter(labels.tolist())
    floor = max(MIN_LINES, MIN_SHARE * labels.size)
    real = [label for label, count in counts.items() if count >= floor]
    if not real:
        return np.zeros_like(labels)
    centres = {
        label: _unit(prints[labels == label].mean(axis=0)) for label in real
    }
    result = labels.copy()
    for index, label in enumerate(labels):
        if label not in centres:
            result[index] = max(real, key=lambda r: float(prints[index] @ centres[r]))
    # Numbered from 0 by size, so speaker 0 is whoever talks most.
    order = [label for label, _ in Counter(result.tolist()).most_common()]
    return np.array([order.index(label) for label in result])


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def speaker_of(labels: list[int | None], spans: Sequence | None = None) -> list[int]:
    """Every span a speaker: an unrecognised one takes a neighbour's.

    With `spans`, the neighbour nearer in time -- «Hi,» said just before
    «listeners, welcome to the show» is the host's, however long the guest
    spoke before it (it went to the guest, measured, when the rule was
    "the one before"). Without, the nearer by position, the one before on
    a tie.
    """
    known = [index for index, label in enumerate(labels) if label is not None]
    if not known:
        return [0] * len(labels)

    def gap(index: int, other: int) -> float:
        if spans is None:
            return float(abs(other - index))
        if other < index:
            return max(0.0, spans[index].start - spans[other].end) + (index - other - 1) * 1e3
        return max(0.0, spans[other].start - spans[index].end) + (other - index - 1) * 1e3

    result = []
    for index, label in enumerate(labels):
        if label is not None:
            result.append(label)
            continue
        before = [k for k in known if k < index]
        after = [k for k in known if k > index]
        candidates = ([before[-1]] if before else []) + ([after[0]] if after else [])
        nearest = min(candidates, key=lambda k: (gap(index, k), k > index))
        result.append(labels[nearest])
    return result
