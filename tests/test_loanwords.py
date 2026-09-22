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


def test_a_prompt_is_a_prompt():
    """«Prompt» came out «проспект»; kept in capitals it survives as a name,
    and comes back as the word Russians use."""
    from lt_core.mt.loanwords import restore

    assert germanise("Schreib einen besseren Prompt.", "de") == "Schreib einen besseren PROMPT."
    assert germanise("Die Prompts werden länger.", "de") == "Die PROMPTS werden länger."
    assert restore("Напишите лучше ПРОМПТ.", "de", "ru") == "Напишите лучше промпт."
    assert restore("Хороший PROMPT даст ответы.", "de", "ru") == "Хороший промпт даст ответы."
    assert restore("ПРОМПТЫ становятся длиннее.", "de", "ru") == "промпты становятся длиннее."
    # Nothing is restored from a language that was not germanised.
    assert restore("Хороший PROMPT.", "en", "ru") == "Хороший PROMPT."


def test_an_llm_is_not_a_law_degree():
    # «LLMs mit Tools» came out «степень магистра».
    assert germanise("LLMs mit Tools verbinden", "de") == "LLM-Modelle mit Tools verbinden"
    assert germanise("dem LLM eine Eingabe", "de") == "dem LLM-Modell eine Eingabe"
    assert germanise("ein LLM-Modell", "de") == "ein LLM-Modell"
