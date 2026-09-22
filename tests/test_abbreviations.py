"""Full stops that do not end a sentence."""

from lt_core.abbreviations import is_abbreviation
from lt_core.mt.nllb import split_sentences


def test_common_abbreviations_are_not_sentence_ends():
    for word in ("z.B.", "d.h.", "bzw.", "ca.", "e.g.", "i.e.", "Dr.", "vs.", "(z.B.", "z.", "B."):
        assert is_abbreviation(word), word


def test_ordinary_words_and_numbers_are():
    for word in ("Tools.", "fertig.", "2.", "2019.", "etc.", "usw."):
        assert not is_abbreviation(word), word


def test_a_sentence_with_z_b_reaches_the_translator_whole():
    """«...LLM mit Tools wie z.B.» was translated on its own, with an
    invented verb, and the rest of the sentence separately."""
    text = "Du kannst LLMs mit Tools wie z.B. Gmail verbinden. Das ist neu."
    assert split_sentences(text) == [
        "Du kannst LLMs mit Tools wie z.B. Gmail verbinden.", "Das ist neu.",
    ]
    spaced = "Tools wie z. B. Gmail sind nützlich. Gut."
    assert split_sentences(spaced) == ["Tools wie z. B. Gmail sind nützlich.", "Gut."]
