"""English nouns in German speech, put into German before NLLB reads them."""

from lt_core.mt.loanwords import germanise


def test_the_link_in_a_meeting_is_a_link_not_a_chain_link():
    # «Und der zweite Link hier.» came out «И второе звено здесь.»
    assert germanise("Und der zweite Link hier.", "de") == "Und der zweite Verweis hier."
    assert germanise("Die Links findet ihr unten.", "de") == "Die Verweise findet ihr unten."


def test_features_are_functions():
    assert germanise("Das Feature ist fertig.", "de") == "Das Funktion ist fertig."
    assert germanise("zu viele Features drin", "de") == "zu viele Funktionen drin"
    assert germanise("ein Feature-Set", "de") == "ein Funktion-Set"


def test_left_is_left_alone():
    """Lower-case «links» is "on the left"; so may be «Links» opening a
    sentence."""
    assert germanise("Oben links sehen Sie das Menü.", "de") == "Oben links sehen Sie das Menü."
    assert germanise("Links sehen Sie das Menü.", "de") == "Links sehen Sie das Menü."


def test_only_german_is_touched():
    assert germanise("Send me the link.", "en") == "Send me the link."
    assert germanise("The Feature is done.", "en") == "The Feature is done."
