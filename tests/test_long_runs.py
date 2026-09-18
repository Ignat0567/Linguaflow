"""Day 7: speech the recogniser stopped punctuating.

A real 12-minute recording lost 85% of its translation here. Whisper
punctuated the first minute and then stopped; with no sentence ends, the
whole unpunctuated run reached NLLB as one piece, the model wrote until it hit
its own ceiling and stopped, and nothing anywhere said so.
"""

from __future__ import annotations

import pytest

from lt_core.mt.nllb import MAX_WORDS, split_sentences
from lt_core.mt.translator import SHORT_RATIO, _looks_cut_off


def words(count: int) -> str:
    return " ".join(f"word{index}" for index in range(count))


# -- splitting -----------------------------------------------------------

def test_punctuated_text_still_splits_on_sentences():
    assert split_sentences("First one. Second one! Third?") == [
        "First one.", "Second one!", "Third?",
    ]


def test_a_decimal_is_not_a_sentence_end():
    """The original reason the splitter demands whitespace after a stop."""
    assert split_sentences("It took 3.1 seconds.") == ["It took 3.1 seconds."]


def test_an_unpunctuated_run_is_cut_up_anyway():
    """This is the bug: with no full stops, the run used to go whole."""
    pieces = split_sentences(words(200))
    assert len(pieces) > 1
    assert max(len(piece.split()) for piece in pieces) <= MAX_WORDS


def test_commas_are_preferred_to_cutting_between_words():
    text = ", ".join([words(8)] * 12)
    pieces = split_sentences(text)
    # Every piece but the last ends where a clause ended.
    assert all(piece.endswith(",") for piece in pieces[:-1])


def test_a_single_clause_longer_than_the_limit_is_still_cut():
    """A poor place to cut, and still better than losing the text."""
    pieces = split_sentences(words(150))
    assert max(len(piece.split()) for piece in pieces) <= MAX_WORDS


def test_nothing_is_lost_by_splitting():
    """Rejoining must reproduce the input apart from whitespace at the seams."""
    for text in (words(200), ", ".join([words(9)] * 15),
                 "A sentence. " + words(90) + ". Another one."):
        assert " ".join(split_sentences(text)).split() == text.split()


def test_the_limit_leaves_the_decoder_room():
    """40 English words become about 50 Russian, near 100 tokens; the model
    writes up to 256 by default. The margin is the point."""
    assert MAX_WORDS <= 60


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_empty_text_produces_no_pieces(text):
    assert split_sentences(text) == []


# -- noticing a cut-off translation -------------------------------------

def test_a_translation_half_the_length_is_reported():
    source = "this is a long enough sentence for the ratio to mean something at all"
    assert _looks_cut_off(source, "короткий огрызок", "ru")


def test_a_normal_translation_is_not_reported():
    source = "this is a long enough sentence for the ratio to mean something at all"
    target = "это достаточно длинное предложение чтобы отношение длин вообще что-то значило"
    assert not _looks_cut_off(source, target, "ru")


def test_a_short_input_is_not_judged_by_length():
    """Under a dozen words a legitimate translation can be a single word."""
    assert not _looks_cut_off("yes of course", "да", "ru")


def test_an_empty_translation_is_left_to_the_empty_check():
    assert not _looks_cut_off("a sentence long enough to be judged by its length", "", "ru")


def test_languages_written_without_spaces_are_exempt():
    """Chinese genuinely says the same thing in far fewer characters, so the
    ratio there measures the script, not a truncation."""
    source = "this is a long enough sentence for the ratio to mean something at all"
    assert not _looks_cut_off(source, "这是一个足够长的句子", "zh")


def test_the_threshold_is_far_below_any_working_pair():
    """Russian runs longer than English, German longer still. Nothing real
    lands near a half."""
    assert SHORT_RATIO <= 0.6
