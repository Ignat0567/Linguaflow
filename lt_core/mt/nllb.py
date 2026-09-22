"""Offline translation with NLLB-200, run through CTranslate2.

Two things about this model shape the code around it, both measured during the
Day 0 spike rather than read in documentation.

It is trained on single sentences, and given several it silently drops some.
Asked for English to Chinese on a three-sentence paragraph it returned two
sentences, having discarded the greeting entirely -- while the same input to
German came back complete. The failure depends on the language pair, so it
survives any test that only checks one. Everything is therefore split into
sentences and translated as a batch, which also turned out to be faster than
passing the paragraph whole.

It also mistranslates numbers. "twelve thousand dollars" came back as 12万美元,
which is a hundred and twenty thousand -- a factor of ten, on a financial
figure, in fluent and entirely convincing Chinese. Hiding numbers behind
placeholders was the obvious defence and was measured not to work; what happens
instead is an audit afterwards, in lt_core.mt.numbers.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .. import languages
from ..runtime import bootstrap
from .loanwords import germanise
from .types import NLLB_CODES, TranslationError

#: The larger distilled model, int8. Measured on German meeting speech
#: against the 600M one: «nüchterner» came out «более трезво» where 600M
#: said «чаще», «Ich gehe von diesem Rahmen aus» «Я буду исходить из этой
#: рамки» where 600M said «Пойду с этой точки зрения». 0.35 s a sentence on
#: the GPU against 0.2 s; 1.4 GB to fetch once.
DEFAULT_MODEL = "OpenNMT/nllb-200-distilled-1.3B-ct2-int8"
#: Used when the default cannot be had -- offline on a first run, with the
#: smaller model already on disk.
FALLBACK_MODEL = "entai2965/nllb-200-distilled-600M-ctranslate2"

# Sentence boundaries, in two flavours, because the two scripts disagree about
# whitespace.
#
# A Latin sentence end must be followed by a space. Without that requirement
# "3.1 seconds" splits into two sentences and the figure is destroyed.
#
# A CJK sentence end must not require one: the terminators are written flush
# against the next sentence. Demanding whitespace there made this function a
# no-op for Chinese and Japanese -- which is exactly where the sentence-dropping
# it exists to prevent was measured. The paragraph would have reached the model
# whole, and the model would have dropped part of it.
_SENTENCE = re.compile(
    r"(?<=[.!?…])['\"»”’)\]]*\s+"
    r"|(?<=[。！？])['\"»”’)\]］】」』]*\s*"
)


#: Clause boundaries, used when a stretch of speech has no sentence ends in it
#: at all. Weaker than a full stop and far better than nothing.
_CLAUSE = re.compile(r"(?<=[,;:—–])\s+")

#: The longest piece handed to the model, in words.
#:
#: Not a style preference -- a hard limit measured against the model. NLLB
#: distilled reads at most 1024 tokens and writes at most 256, and the writing
#: limit binds first: a 1331-word block came back as 160 words, the other 85%
#: silently gone and the translation cut off mid-clause. Forty words of English
#: become roughly fifty of Russian, near a hundred tokens, which leaves the
#: decoder most of its room spare.
MAX_WORDS = 40


def _break_up(part: str) -> list[str]:
    """Cut an over-long stretch at the best boundary available.

    Commas first, because a clause boundary is a real boundary and the model
    translates a clause well. Only when a single clause is still too long is
    the text cut between words, which is a poor place to cut and still far
    better than the alternative, which is losing it.
    """
    if len(part.split()) <= MAX_WORDS:
        return [part]

    pieces: list[str] = []
    current: list[str] = []
    length = 0
    for clause in _CLAUSE.split(part):
        words = clause.split()
        if not words:
            continue
        if current and length + len(words) > MAX_WORDS:
            pieces.append(" ".join(current))
            current, length = [], 0
        if len(words) > MAX_WORDS:
            if current:
                pieces.append(" ".join(current))
                current, length = [], 0
            for start in range(0, len(words), MAX_WORDS):
                pieces.append(" ".join(words[start:start + MAX_WORDS]))
            continue
        current.extend(words)
        length += len(words)
    if current:
        pieces.append(" ".join(current))
    return pieces or [part]


def split_sentences(text: str) -> list[str]:
    """Divide text into pieces the model can translate whole.

    Sentences where there are sentences. Where there are none -- and there are
    none whenever the recogniser stops punctuating, which it does -- the run is
    cut at clause boundaries instead, because handing the model more than it
    can read means it answers with part of the text and no warning.

    Rejoining the pieces must reproduce the input apart from the whitespace at
    the seams, so nothing can be lost here before the model has even seen it.
    """
    stripped = text.strip()
    if not stripped:
        return []
    pieces: list[str] = []
    for part in _SENTENCE.split(stripped):
        part = part.strip()
        if part:
            pieces.extend(_break_up(part))
    return pieces


class NllbTranslator:
    """NLLB-200 distilled, int8, on GPU where one is available."""

    name = "NLLB-200 (локально)"
    is_offline = True
    # This model answers a one-word input with an invented dialogue turn; see
    # RISKY_WORD_COUNT in lt_core.mt.translator. It is a property of this model,
    # not of running locally, so it is declared here rather than inferred.
    unreliable_on_short_input = True

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        device: str = "auto",
        compute_type: str | None = None,
        model_root: Path | str | None = None,
        beam_size: int = 4,
    ) -> None:
        bootstrap(model_root)
        import ctranslate2
        import transformers

        self.beam_size = beam_size
        self.device, self.compute_type = _choose_device(device, compute_type)

        try:
            path = _resolve_model(model)
        except TranslationError:
            if model != DEFAULT_MODEL:
                raise
            path = _resolve_model(FALLBACK_MODEL)
        try:
            self._translator = ctranslate2.Translator(
                path, device=self.device, compute_type=self.compute_type
            )
        except Exception as exc:
            raise TranslationError(
                "Не удалось загрузить локальную модель перевода.", str(exc)
            ) from exc
        self._model_path = path
        self._tokenizers: dict[str, object] = {}
        self._transformers = transformers

    def supports(self, source: str, target: str) -> bool:
        return source in NLLB_CODES and target in NLLB_CODES and source != target

    def _tokenizer(self, source: str):
        """One tokenizer per source language: the code is baked in at load.

        transformers 5.x prints a warning here recommending
        `fix_mistral_regex=True`, and claiming that without it "this will lead
        to incorrect tokenization". Following that advice was measured against
        eight English sentences translated to Russian, and it destroys this
        model:

            "We went from roughly 9 incidents a month to 2."
              default  -> Мы выросли с 9 инцидентов в месяц до 2.
              flagged  -> Мы перешли от происшествий, происшествий,
                          происшествий, происшествий.

            "Candidates are waiting 11 days between the interview and an offer."
              default  -> Кандидаты ждут 11 дней между собеседованием и предложением.
              flagged  -> Кандидаты ждут интервью и предложение.

        Six of eight outputs changed, several into degenerate repetition, and
        numbers disappeared outright. The warning is about Mistral tokenizers
        and does not apply to NLLB's SentencePiece; acting on it would silently
        delete the very figures the audit downstream exists to protect.

        So the flag stays off and the warning is silenced, because a warning
        nobody may act on is noise in front of a user.
        """
        if source not in self._tokenizers:
            logging = self._transformers.utils.logging
            previous = logging.get_verbosity()
            logging.set_verbosity_error()
            try:
                self._tokenizers[source] = (
                    self._transformers.AutoTokenizer.from_pretrained(
                        self._model_path, src_lang=NLLB_CODES[source]
                    )
                )
            finally:
                logging.set_verbosity(previous)
        return self._tokenizers[source]

    def translate(self, texts: list[str], source: str, target: str) -> list[str]:
        if not self.supports(source, target):
            raise TranslationError(
                f"Пара {source} → {target} не поддерживается локальной моделью."
            )
        if not texts:
            return []

        tokenizer = self._tokenizer(source)
        target_code = NLLB_CODES[target]

        # Flatten every entry's sentences into one batch, remembering which
        # entry each came from, so the model sees sentences and the caller
        # still gets one result per input.
        batch: list[list[str]] = []
        ownership: list[int] = []
        for position, text in enumerate(texts):
            for sentence in split_sentences(text):
                sentence = germanise(sentence, source)
                batch.append(tokenizer.convert_ids_to_tokens(tokenizer.encode(sentence)))
                ownership.append(position)

        if not batch:
            return ["" for _ in texts]

        try:
            responses = self._translator.translate_batch(
                batch,
                target_prefix=[[target_code]] * len(batch),
                beam_size=self.beam_size,
                max_batch_size=32,
                # The default of 256 is what truncated a long run before the
                # pieces were capped. Pieces are small now, so this ceiling
                # should never be reached -- it is raised anyway, because
                # reaching it costs the rest of the sentence.
                max_decoding_length=512,
            )
        except Exception as exc:
            raise TranslationError("Сбой локального перевода.", str(exc)) from exc

        collected: list[list[str]] = [[] for _ in texts]
        for owner, response in zip(ownership, responses):
            # The first token is the target-language tag the model echoes back.
            tokens = response.hypotheses[0][1:]
            collected[owner].append(
                tokenizer.decode(tokenizer.convert_tokens_to_ids(tokens)).strip()
            )

        joiner = " " if languages.joins_with_space(target) else ""
        return [
            _strip_subtitle_artefacts(
                joiner.join(part for part in parts if part), texts[position]
            )
            for position, parts in enumerate(collected)
        ]


_LEADING_DASH = re.compile(r"^\s*[-–—]\s*")
_SENTENCE_PIECES = re.compile(r"(?<=[.!?…。！？])\s*")


def _strip_subtitle_artefacts(translated: str, source: str) -> str:
    """Remove the dialogue formatting NLLB invents for short inputs.

    A large part of NLLB's training data is subtitle corpora, where a short
    line is a dialogue turn written with a leading dash. Give it a bare short
    sentence and it produces a plausible dialogue turn rather than a
    translation. Measured on seven one-word English inputs: a leading dash
    appeared in seven of seven Russian outputs and six of seven German ones,
    and two came back with the sentence repeated -- "Спасибо. - Спасибо."

    Both artefacts are removed here, and only when the source did not have
    them: a real dash in the original is left alone.

    This does not fix the deeper problem. The same measurement produced "Yes."
    -> "Нет, нет." -- the opposite meaning -- which no amount of tidying can
    repair. That is addressed upstream, by giving the model whole sentences
    instead of fragments; see lt_core.subtitles.bilingual.
    """
    if not translated:
        return translated

    if not _LEADING_DASH.match(source):
        translated = _LEADING_DASH.sub("", translated)
        # A repetition often carries its own dash: "Спасибо. - Спасибо."
        translated = re.sub(r"\s+[-–—]\s+", " ", translated)

    pieces = [piece.strip() for piece in _SENTENCE_PIECES.split(translated) if piece.strip()]
    if len(pieces) > 1 and len(set(pieces)) == 1:
        # The model said the same sentence twice; the source said it once.
        source_pieces = [
            piece.strip() for piece in _SENTENCE_PIECES.split(source) if piece.strip()
        ]
        if len(source_pieces) < len(pieces):
            translated = pieces[0]

    return translated.strip()


def _resolve_model(model: str) -> str:
    """Accept a local directory or a hub id, downloading the latter once."""
    candidate = Path(model)
    if candidate.exists():
        return str(candidate.resolve())

    from huggingface_hub import snapshot_download

    try:
        return snapshot_download(model)
    except Exception as exc:
        raise TranslationError(
            f"Не удалось получить модель перевода «{model}». "
            f"Для первой загрузки нужен интернет.",
            str(exc),
        ) from exc


def _choose_device(device: str, compute_type: str | None) -> tuple[str, str]:
    if device == "auto":
        try:
            import ctranslate2

            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    if compute_type is None:
        compute_type = "int8_float16" if device == "cuda" else "int8"
    return device, compute_type
