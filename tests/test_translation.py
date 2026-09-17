"""Day 3: translation, its safeguards, and bilingual output."""

from __future__ import annotations

from decimal import Decimal

import pytest

from lt_core.mt.glossary import Glossary
from lt_core.mt.nllb import split_sentences
from lt_core.mt.numbers import audit, compare, extract
from lt_core.mt.translator import Translator, build_translator
from lt_core.mt.types import TranslationError, TranslationMode
from lt_core.subtitles.bilingual import merge_bilingual, translate_cues
from lt_core.subtitles.cues import Cue


class FakeProvider:
    """A provider that records what it was asked and returns what it is told."""

    name = "fake"

    def __init__(self, outputs=None, offline=True, pairs=None) -> None:
        self.is_offline = offline
        self.outputs = outputs
        self.calls: list[list[str]] = []
        self.pairs = pairs

    def supports(self, source: str, target: str) -> bool:
        if self.pairs is not None:
            return (source, target) in self.pairs
        return source != target

    def translate(self, texts, source, target):
        self.calls.append(list(texts))
        if self.outputs is not None:
            return list(self.outputs)
        return [f"[{target}] {text}" for text in texts]


def cue(index: int, start: float, end: float, *lines: str) -> Cue:
    return Cue(index=index, start=start, end=end, lines=tuple(lines))


# -- sentence splitting --------------------------------------------------

def test_paragraph_is_split_into_sentences():
    """NLLB drops sentences when given several at once.

    Measured on the spike: an English paragraph of three sentences came back
    from Chinese with the greeting missing, while German came back complete.
    The loss depends on the language pair, so it survives any check that only
    looks at one.
    """
    parts = split_sentences(
        "Good morning. Our team cut latency by 31%. Thank you all."
    )
    assert len(parts) == 3
    assert parts[0] == "Good morning."


def test_splitting_keeps_every_word():
    text = "One thing happened. Then another! And a third? Finally this."
    assert " ".join(split_sentences(text)) == text


def test_splitting_handles_cjk_terminators():
    assert len(split_sentences("皆さん、おはよう。今日は良い天気です。")) == 2


def test_splitting_does_not_break_on_decimals():
    """"3.1 seconds" is not two sentences."""
    assert split_sentences("Latency was 3.1 seconds on average.") == [
        "Latency was 3.1 seconds on average."
    ]


def test_empty_text_yields_nothing():
    assert split_sentences("   ") == []


# -- number auditing -----------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("12,000", ["12000"]),
    ("12.000", ["12000"]),
    ("12 000", ["12000"]),
    ("3.1", ["3.1"]),
    ("3,1", ["3.1"]),
    ("4.7 million dollars", ["4700000"]),
    ("4,7 Millionen Dollar", ["4700000"]),
    ("4,7 миллиона долларов", ["4700000"]),
    ("47万美元", ["470000"]),
    ("470万ドル", ["4700000"]),
    ("1万2千ドル", ["12000"]),
    ("31%", ["31"]),
    ("420 milliseconds to 290", ["420", "290"]),
])
def test_numbers_are_extracted_whatever_the_notation(text, expected):
    assert [format(v.normalize(), "f") for v in extract(text)] == expected


def test_numbers_are_found_flush_against_cjk_text():
    """Regression: a word-boundary guard hid every number in Chinese.

    CJK writes numbers with no space around them -- 削减了12,000美元 -- and \\w
    matches CJK characters, so a \\b-style lookbehind made the audit blind
    exactly where it was needed. An audit that cannot see numbers reports
    success on corrupted text.
    """
    assert extract("我们每月削减了12,000美元。") == [Decimal(12000)]


def test_audit_flags_the_ten_fold_error():
    """The real failure this exists for: 4.7 million rendered as 470,000."""
    missing, added = compare(
        "Revenue grew 31% to 4.7 million dollars.",
        "收入增长了31%,达到47万美元.",
    )
    assert "4700000" in missing
    assert "470000" in added


def test_audit_accepts_a_different_notation_for_the_same_value():
    """1万2千 and $12,000 are the same number written two ways."""
    assert compare(
        "We cut spending by $12,000 per month.",
        "毎月1万2千ドル削減しました",
    ) == ((), ())


def test_audit_is_quiet_on_a_clean_translation():
    assert compare(
        "Latency fell from 420 milliseconds to 290.",
        "Die Latenz fiel von 420 Millisekunden auf 290.",
    ) == ((), ())


def test_audit_reports_position_and_values():
    found = audit(
        ["Revenue grew to 4.7 million.", "Nothing numeric here."],
        ["收入增长到47万.", "Ничего числового."],
    )
    assert len(found) == 1
    assert found[0].index == 0
    assert "пропало" in found[0].describe()


def test_audit_ignores_word_order():
    """Reversal is a different bug; this check is about values surviving."""
    assert compare("from 9 to 2", "von 2 auf 9") == ((), ())


# -- glossary ------------------------------------------------------------

def test_glossary_forces_the_wanted_rendering():
    glossary = Glossary()
    glossary.add("Sentinel", {"de": "Sentinel"})
    assert "Sentinel" in glossary.apply("Sentinel is running", "Wachposten läuft", "de")


def test_glossary_leaves_untouched_text_alone():
    glossary = Glossary()
    glossary.add("Sentinel", {"de": "Sentinel"})
    assert glossary.apply("nothing here", "nichts hier", "de") == "nichts hier"


def test_glossary_accepts_a_correct_translation_unchanged():
    glossary = Glossary()
    glossary.add("Acme", {"ru": "Acme"})
    assert glossary.apply("Acme ships", "Acme отгружает", "ru") == "Acme отгружает"


def test_glossary_matches_whole_words_only():
    """Protecting "Alex" must not rewrite "Alexandra"."""
    glossary = Glossary()
    glossary.add("Alex", {"de": "Alex"})
    assert glossary.terms_in("Alexandra arrived") == []
    assert glossary.terms_in("Alex arrived") == ["Alex"]


def test_glossary_prefers_the_longest_match():
    glossary = Glossary()
    glossary.add("Acme", {})
    glossary.add("Acme Corporation", {})
    assert glossary.terms_in("Acme Corporation ships")[0] == "Acme Corporation"


def test_glossary_loads_from_csv(tmp_path):
    path = tmp_path / "terms.csv"
    path.write_text("term,de,ru\nSentinel,Sentinel,Sentinel\nAcme,Acme,Акме\n",
                    encoding="utf-8")
    glossary = Glossary.load(path)
    assert len(glossary) == 2
    assert glossary.wanted("Acme", "ru") == "Акме"


def test_glossary_loads_from_json(tmp_path):
    path = tmp_path / "terms.json"
    path.write_text('{"Sentinel": {"de": "Sentinel"}}', encoding="utf-8")
    assert Glossary.load(path).wanted("Sentinel", "de") == "Sentinel"


def test_missing_glossary_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        Glossary.load(tmp_path / "absent.csv")


# -- translator ----------------------------------------------------------

def test_translation_preserves_order_and_count():
    translator = Translator(FakeProvider())
    results, report = translator.translate(["one", "two", "three"], "en", "de")
    assert results == ["[de] one", "[de] two", "[de] three"]
    assert report.count == 3


def test_a_provider_returning_the_wrong_count_is_refused():
    """Results are matched to timings by position.

    A provider that returns four translations for five inputs would shift every
    subsequent subtitle onto someone else's timestamp -- silently, and for the
    rest of the file.
    """
    translator = Translator(FakeProvider(outputs=["only one"]))
    with pytest.raises(TranslationError, match="соответствие"):
        translator.translate(["a", "b", "c"], "en", "de")


def test_repeated_lines_are_translated_once():
    provider = FakeProvider()
    translator = Translator(provider)
    _, report = translator.translate(["hello", "hello", "bye"], "en", "de")
    assert provider.calls == [["hello", "bye"]]
    assert report.cache_hits == 1


def test_blank_lines_never_reach_the_provider():
    provider = FakeProvider()
    results, _ = Translator(provider).translate(["", "  ", "text"], "en", "de")
    assert provider.calls == [["text"]]
    assert results[0] == "" and results[1] == ""


def test_translating_into_the_same_language_is_refused():
    with pytest.raises(TranslationError, match="совпадают"):
        Translator(FakeProvider()).translate(["x"], "en", "en")


def test_unsupported_pair_is_refused_by_name():
    translator = Translator(FakeProvider(pairs={("en", "de")}))
    with pytest.raises(TranslationError, match="ru"):
        translator.translate(["x"], "en", "ru")


def test_report_names_where_the_text_went():
    offline, _ = Translator(FakeProvider(offline=True)).translate(["x"], "en", "de")
    _, report = Translator(FakeProvider(offline=False)).translate(["x"], "en", "de")
    assert report.offline is False


def test_offline_mode_never_becomes_online_silently():
    """The mode is a promise about where the user's words go.

    Falling back to a cloud service because the local model failed would break
    that promise precisely when it mattered -- a confidential call, a medical
    consultation -- and the user would never know.
    """
    with pytest.raises(TranslationError, match="Неизвестный режим"):
        build_translator("whatever-mode")


def test_mode_constants_are_distinct():
    assert TranslationMode.OFFLINE != TranslationMode.ONLINE


def test_number_mismatches_reach_the_report():
    provider = FakeProvider(outputs=["收入增长到47万."])
    _, report = Translator(provider).translate(
        ["Revenue grew to 4.7 million."], "en", "zh"
    )
    assert report.needs_review
    assert len(report.number_mismatches) == 1


def test_empty_translation_is_reported_not_hidden():
    provider = FakeProvider(outputs=[""])
    _, report = Translator(provider).translate(["something was said"], "en", "de")
    assert report.empty_results == [0]
    assert report.needs_review


# -- numbered replies from an LLM ---------------------------------------

def test_numbered_reply_is_parsed_back_in_order():
    from lt_core.mt.cloud import _parse_numbered

    assert _parse_numbered("1. eins\n2. zwei\n3. drei", 3) == ["eins", "zwei", "drei"]


def test_a_missing_line_in_a_numbered_reply_is_fatal():
    """Silently dropping a line shifts every subtitle after it."""
    from lt_core.mt.cloud import _parse_numbered

    with pytest.raises(TranslationError, match="не все строки"):
        _parse_numbered("1. eins\n3. drei", 3)


# -- bilingual output ----------------------------------------------------

def test_translation_does_not_move_timings():
    """The words were spoken when they were spoken."""
    original = (cue(1, 0.0, 2.0, "Hello there"), cue(2, 2.5, 4.0, "Goodbye"))
    translated = translate_cues(original, ["Привет", "До свидания"])
    assert [(c.start, c.end) for c in translated] == [(0.0, 2.0), (2.5, 4.0)]


def test_translated_cue_keeps_the_original_when_translation_is_empty():
    original = (cue(1, 0.0, 2.0, "Hello there"),)
    assert translate_cues(original, [""])[0].lines == ("Hello there",)


def test_mismatched_translation_count_is_refused():
    original = (cue(1, 0.0, 2.0, "a"), cue(2, 2.0, 4.0, "b"))
    with pytest.raises(ValueError, match="соответствие"):
        translate_cues(original, ["one"])


def test_bilingual_cue_shows_translation_first():
    original = (cue(1, 0.0, 2.0, "Good morning"),)
    translated = (cue(1, 0.0, 2.0, "Доброе утро"),)
    merged = merge_bilingual(original, translated)
    assert merged[0].lines == ("Доброе утро", "Good morning")


def test_bilingual_order_can_be_reversed():
    original = (cue(1, 0.0, 2.0, "Good morning"),)
    translated = (cue(1, 0.0, 2.0, "Доброе утро"),)
    merged = merge_bilingual(original, translated, translation_first=False)
    assert merged[0].lines[0] == "Good morning"


def test_bilingual_refuses_unequal_lists():
    with pytest.raises(ValueError):
        merge_bilingual((cue(1, 0.0, 1.0, "a"),), ())


# -- line wrapping under translation expansion ---------------------------

def test_longer_translation_wraps_across_balanced_lines():
    """Russian runs longer than English; a third line must not be a stub.

    A greedy fill left "рецензии." alone on a line while the two above it were
    32 and 36 characters wide.
    """
    from lt_core.subtitles.cues import CueStyle, _wrap

    lines = _wrap(
        "Доброе утро всем, и спасибо, что присоединились к этой "
        "ежеквартальной рецензии.",
        CueStyle(),
    )
    widths = [len(line) for line in lines]
    assert max(widths) <= CueStyle().max_chars_per_line
    assert max(widths) - min(widths) <= 8


def test_wrapping_never_drops_words():
    from lt_core.subtitles.cues import CueStyle, _wrap

    text = ("Wir haben die durchschnittliche Antwortzeit deutlich reduziert "
            "und die Infrastrukturkosten deutlich gesenkt.")
    assert " ".join(_wrap(text, CueStyle())) == text


# -- artefacts of a subtitle-trained model -------------------------------

def test_invented_dialogue_dash_is_removed():
    """NLLB writes a leading dash on short lines.

    It was trained on subtitle corpora where a short line is a dialogue turn.
    Measured on seven one-word English inputs: a dash appeared in seven of
    seven Russian outputs and six of seven German ones.
    """
    from lt_core.mt.nllb import _strip_subtitle_artefacts

    assert _strip_subtitle_artefacts("- Доброе утро.", "Good morning.") == "Доброе утро."


def test_a_dash_present_in_the_source_is_kept():
    from lt_core.mt.nllb import _strip_subtitle_artefacts

    assert _strip_subtitle_artefacts("- Да, конечно.", "- Of course.").startswith("-")


def test_repeated_sentence_is_collapsed():
    """The model said it twice; the speaker said it once."""
    from lt_core.mt.nllb import _strip_subtitle_artefacts

    assert _strip_subtitle_artefacts("Спасибо. Спасибо.", "Thanks.") == "Спасибо."


def test_genuine_repetition_in_the_source_survives():
    from lt_core.mt.nllb import _strip_subtitle_artefacts

    result = _strip_subtitle_artefacts("Нет. Нет.", "No. No.")
    assert result == "Нет. Нет."


def test_short_inputs_are_flagged_for_review():
    """"Yes." came back as "Нет, нет." -- the opposite. Unfixable, so visible."""
    translator = Translator(FakeProvider(offline=True))
    _, report = translator.translate(
        ["Yes.", "A sentence with a good many words in it."], "en", "ru"
    )
    assert report.risky_short == [0]
    assert report.needs_review


def test_short_inputs_are_not_flagged_for_a_cloud_provider():
    """The warning is about this local model, not about short text."""
    translator = Translator(FakeProvider(offline=False))
    _, report = translator.translate(["Yes."], "en", "ru")
    assert report.risky_short == []


# -- sentence grouping ---------------------------------------------------

def test_cues_of_one_sentence_are_grouped():
    """A sentence spanning three cues must reach the model whole."""
    from lt_core.subtitles.bilingual import group_into_sentences

    cues = (
        cue(1, 0.0, 2.0, "We cut infrastructure spending"),
        cue(2, 2.0, 4.0, "by roughly twelve thousand"),
        cue(3, 4.0, 6.0, "dollars per month."),
        cue(4, 6.0, 8.0, "Thank you all."),
    )
    assert group_into_sentences(cues) == [[0, 1, 2], [3]]


def test_a_trailing_fragment_still_forms_a_group():
    from lt_core.subtitles.bilingual import group_into_sentences

    cues = (cue(1, 0.0, 2.0, "An unfinished thought"),)
    assert group_into_sentences(cues) == [[0]]


def test_cjk_sentence_end_closes_a_group():
    from lt_core.subtitles.bilingual import group_into_sentences

    cues = (cue(1, 0.0, 2.0, "大家早上好。"), cue(2, 2.0, 4.0, "感谢各位。"))
    assert group_into_sentences(cues) == [[0], [1]]


def test_translation_is_distributed_across_the_cues_it_covers():
    from lt_core.subtitles.bilingual import distribute

    parts = distribute("один два три четыре пять шесть", [10, 10, 10])
    assert len(parts) == 3
    assert " ".join(parts) == "один два три четыре пять шесть"


def test_distribution_never_leaves_a_cue_empty():
    from lt_core.subtitles.bilingual import distribute

    parts = distribute("один два три четыре", [40, 5, 5])
    assert all(part for part in parts)


def test_distribution_of_a_single_cue_is_the_whole_text():
    from lt_core.subtitles.bilingual import distribute

    assert distribute("целиком", [10]) == ["целиком"]


def test_distribution_loses_nothing_with_more_cues_than_words():
    from lt_core.subtitles.bilingual import distribute

    parts = distribute("два слова", [10, 10, 10])
    assert " ".join(p for p in parts if p) == "два слова"


def test_cjk_translation_is_distributed_by_character():
    from lt_core.subtitles.bilingual import distribute

    parts = distribute("大家早上好感谢各位", [10, 10], join_with_space=False)
    assert "".join(parts) == "大家早上好感谢各位"


# -- batch deduplication -------------------------------------------------

def test_duplicates_within_one_batch_are_translated_once():
    provider = FakeProvider()
    translator = Translator(provider)
    results, report = translator.translate(["hello", "hello", "bye"], "en", "de")
    assert provider.calls == [["hello", "bye"]]
    assert results[0] == results[1]
    assert report.cache_hits == 1


def test_deduplication_keeps_every_position_aligned():
    """Positions carry timings; a shift here misdates every later subtitle."""
    provider = FakeProvider()
    texts = ["a", "b", "a", "c", "b", "", "a"]
    results, _ = Translator(provider).translate(texts, "en", "de")
    assert len(results) == len(texts)
    assert results[5] == ""
    for left, right in zip(texts, results):
        if left:
            assert right == f"[de] {left}"
