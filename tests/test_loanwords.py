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


def test_a_prompt_declines_as_the_request_the_model_translates_it_as():
    """«Prompt» came out «проспект», and kept as a name it would not
    decline: «инженерия промпт». Into Russian it goes as «Abfrage», which
    declines as «промпт» does, and the stem is swapped back."""
    from lt_core.mt.loanwords import restore

    original = "Dafür brauchst du gutes Prompt-Engineering."
    assert germanise(original, "de", "ru") == "Dafür brauchst du gutes Abfrage-Engineering."
    assert restore("Нужна хорошая инженерия запросов.", original, "de", "ru") == (
        "Нужна хорошая инженерия промптов."
    )
    two = "Ich habe drei Prompts probiert."
    assert germanise(two, "de", "ru") == "Ich habe drei Abfragen probiert."
    assert restore("Я пробовал три разных запроса.", two, "de", "ru") == (
        "Я пробовал три разных промпта."
    )
    assert restore("Вопросы становятся длиннее.", "Die Prompts werden länger.", "de", "ru") == (
        "Промпты становятся длиннее."
    )


def test_only_as_many_requests_become_prompts_as_there_were_prompts():
    from lt_core.mt.loanwords import restore

    original = "Kopiere diesen Prompt."
    assert restore("Скопируйте этот запрос, а потом запрос ещё раз.", original, "de", "ru") == (
        "Скопируйте этот промпт, а потом запрос ещё раз."
    )


def test_a_sentence_with_its_own_question_keeps_prompt_as_a_name():
    """Its «вопрос» is a real one and must not become «промпт»."""
    from lt_core.mt.loanwords import restore

    original = "Die Frage ist, welcher Prompt besser ist."
    assert germanise(original, "de", "ru") == "Die Frage ist, welcher PROMPT besser ist."
    assert restore("Вопрос в том, какой ПРОМПТ лучше.", original, "de", "ru") == (
        "Вопрос в том, какой промпт лучше."
    )


def test_into_english_a_prompt_stays_a_prompt():
    from lt_core.mt.loanwords import restore

    original = "Schreib einen besseren Prompt."
    assert germanise(original, "de", "en") == "Schreib einen besseren PROMPT."
    assert restore("Write a better PROMPT.", original, "de", "en") == "Write a better prompt."
    # Nothing is restored from a language that was not germanised.
    assert restore("Хороший PROMPT.", "A good PROMPT.", "en", "ru") == "Хороший PROMPT."


def test_an_llm_is_not_a_law_degree():
    # «LLMs mit Tools» came out «степень магистра».
    assert germanise("LLMs mit Tools verbinden", "de") == "LLM-Modelle mit Tools verbinden"
    assert germanise("dem LLM eine Eingabe", "de") == "dem LLM-Modell eine Eingabe"
    assert germanise("ein LLM-Modell", "de") == "ein LLM-Modell"
