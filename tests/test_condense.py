"""Day 7: shortening a translation so it can be said in the time available.

A dub has a constraint subtitles do not. Speaking faster buys 15-20%, Russian
runs longer than English, and on a fast speaker 42% of the lines did not fit.
Measured on a real recording: the median line needed 11% taken off.
"""

from __future__ import annotations

import pytest

from lt_core.mt.condense import (
    NEGATIONS,
    REPLACEMENTS,
    budget_for,
    condense,
    condense_cues,
    slot_seconds,
)
from lt_core.mt.numbers import extract
from lt_core.mt.shorten_with_model import can_shorten, shorten_cues
from lt_core.subtitles.cues import Cue


def cue(index: int, start: float, end: float, text: str) -> Cue:
    return Cue(index=index, start=start, end=end, lines=(text,))


# -- what it removes -----------------------------------------------------

def test_a_line_that_fits_is_left_alone():
    """Nothing is shortened for its own sake."""
    result = condense("Короткая фраза.", 100, "ru")
    assert not result.changed
    assert result.text == "Короткая фраза."


def test_filler_goes_first():
    result = condense("Вы знаете, это работает хорошо.", 22, "ru")
    assert "Вы знаете" not in result.text
    assert "работает хорошо" in result.text


def test_a_long_connective_becomes_a_short_one():
    result = condense("Он пришёл для того чтобы помочь нам всем сегодня.", 40, "ru")
    assert "для того чтобы" not in result.text
    assert "чтобы" in result.text


def test_shortening_stops_as_soon_as_the_line_fits():
    """Emphasis is part of what a speaker meant; it is not removed for sport."""
    text = "Вы знаете, это очень действительно просто и совершенно понятно."
    generous = condense(text, len(text) - 12, "ru")
    aggressive = condense(text, 20, "ru")
    assert len(generous.steps) < len(aggressive.steps)


def test_the_opening_capital_survives_a_removal_at_the_front():
    result = condense("Вы знаете, это работает.", 15, "ru")
    assert result.text[:1].isupper()


def test_a_lower_case_opening_is_not_capitalised():
    result = condense("вы знаете, это работает.", 15, "ru")
    assert result.text[:1].islower()


@pytest.mark.parametrize("language", ["ru", "en", "de"])
def test_every_offered_language_has_rules(language):
    assert REPLACEMENTS.get(language)
    assert NEGATIONS.get(language)


# -- what it refuses to touch -------------------------------------------

def test_a_figure_is_never_lost():
    """A dub that says a different number is worse than one that runs over."""
    text = "Вы знаете, этот канал приносит 12000 долларов в месяц."
    result = condense(text, 20, "ru")
    assert extract(result.text) == extract(text)


def test_a_negation_is_never_dropped():
    """Removing «не» inverts the sentence, which is the worst outcome here."""
    text = "На самом деле это не работает так, как вы думаете."
    result = condense(text, 15, "ru")
    assert result.text.count("не") >= text.count("не")


def test_nothing_is_reduced_to_nothing():
    result = condense("Вы знаете, понимаете, в общем.", 1, "ru")
    assert result.text.strip()


def test_no_replacement_substitutes_an_inflected_noun():
    """Russian inflects, and a noun swapped in the nominative lands in the
    wrong case: «программное обеспечение» for «программа» produced «открыть
    программа». Only phrases that agree with nothing may be replaced.
    """
    banned = ("программное обеспечение", "с помощью", "в течение",
              "которые требуются для")
    for long_form, _short in REPLACEMENTS["ru"]:
        assert long_form not in banned, long_form


# -- the time a line actually has ---------------------------------------

def test_a_line_may_use_the_silence_before_the_next_one():
    """Free and lossless: on a real recording this alone took the lines that
    do not fit from 75 to 59."""
    cues = (cue(1, 0.0, 1.0, "раз"), cue(2, 3.0, 4.0, "два"))
    assert slot_seconds(cues, 0) == pytest.approx(3.0)


def test_the_last_line_has_only_its_own_time():
    cues = (cue(1, 0.0, 1.0, "раз"), cue(2, 3.0, 4.5, "два"))
    assert slot_seconds(cues, 1) == pytest.approx(1.5)


def test_the_budget_follows_the_voice_that_will_speak():
    """Measured: ruslan says 18.4 characters a second, irina 13.9 -- a third
    apart, so one number for both would be wrong by that much."""
    assert budget_for(2.0, 18.4) > budget_for(2.0, 13.9)


def test_headroom_allows_for_the_speed_up_still_to_come():
    assert budget_for(2.0, 15.0, headroom=1.18) > budget_for(2.0, 15.0)


def test_cues_keep_their_timings_when_shortened():
    """Timings belong to the speech. Only the words may change."""
    cues = (cue(1, 0.0, 1.0, "Вы знаете, это на самом деле очень просто."),)
    out, records = condense_cues(cues, "ru", 10.0, headroom=1.0)
    assert out[0].start == cues[0].start and out[0].end == cues[0].end
    assert records[0].changed


# -- handing the rest to the model --------------------------------------

class FakeProvider:
    """Answers with whatever it is told to, so the checks can be tested."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = answers
        self.asked: list[tuple[str, int]] = []

    def shorten(self, lines, language):
        self.asked = list(lines)
        return self.answers


def long_cues() -> tuple[Cue, ...]:
    return (
        cue(1, 0.0, 2.0,
            "Этот довольно длинный текст никак не помещается в своё время"),
    )


def test_a_provider_that_cannot_rewrite_is_not_asked():
    assert not can_shorten(object())
    assert can_shorten(FakeProvider([]))


def test_each_batch_is_reported_when_it_returns():
    """A slow batch used to be invisible. The ring hears the batches, and a
    batch that failed is still a batch that finished."""

    class OneAtATime:
        shorten_lines_per_request = 1

        def __init__(self) -> None:
            self.calls = 0

        def shorten(self, lines, language):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("этот запрос не вернулся")
            return ["Короче."] * len(lines)

    seen: list[tuple[int, int]] = []
    cues = (
        cue(1, 0.0, 1.0, "Этот довольно длинный текст никак не помещается"),
        cue(2, 2.0, 3.0, "И этот тоже никак не успевает прозвучать целиком"),
    )
    _out, _records, report = shorten_cues(
        cues, "ru", 17.8, OneAtATime(), headroom=1.18,
        on_batch=lambda done, total: seen.append((done, total)),
    )
    assert seen == [(1, 2), (2, 2)]
    assert report.lost == 1


def test_the_model_is_given_the_budget_for_each_line():
    provider = FakeProvider(["Короче."])
    shorten_cues(long_cues(), "ru", 17.8, provider, headroom=1.18)
    assert provider.asked and isinstance(provider.asked[0][1], int)
    assert provider.asked[0][1] > 0


def test_a_shortened_line_that_lost_a_figure_is_discarded():
    cues = (cue(1, 0.0, 1.5,
                "Этот канал приносит 5000 долларов каждый месяц без перерыва"),)
    provider = FakeProvider(["Канал приносит 9000 долларов."])
    out, records, report = shorten_cues(cues, "ru", 17.8, provider, headroom=1.18)
    assert report.rejected_unsafe == 1
    assert out[0].flat_text == cues[0].flat_text
    assert not records[0].changed


def test_a_shortened_line_that_lost_a_negation_is_discarded():
    cues = (cue(1, 0.0, 1.5,
                "Этот довольно длинный текст не помещается в отведённое время"),)
    provider = FakeProvider(["Текст помещается в отведённое время."])
    _out, _records, report = shorten_cues(cues, "ru", 17.8, provider, headroom=1.18)
    assert report.rejected_unsafe == 1


def test_a_line_that_came_back_longer_is_discarded():
    provider = FakeProvider([
        "Этот довольно длинный текст никак не помещается в своё время, "
        "и после переписывания он стал ещё заметно длиннее прежнего."
    ])
    _out, _records, report = shorten_cues(
        long_cues(), "ru", 17.8, provider, headroom=1.18
    )
    assert report.rejected_longer == 1


def test_an_empty_answer_is_discarded():
    provider = FakeProvider(["   "])
    _out, _records, report = shorten_cues(
        long_cues(), "ru", 17.8, provider, headroom=1.18
    )
    assert report.rejected_longer == 1


def test_a_safe_shortening_is_accepted_and_recorded():
    provider = FakeProvider(["Текст не помещается."])
    out, records, report = shorten_cues(
        long_cues(), "ru", 17.8, provider, headroom=1.18
    )
    assert report.accepted == 1
    assert out[0].flat_text == "Текст не помещается."
    assert "сокращено моделью" in records[0].steps


def test_a_failing_provider_leaves_the_dub_alone():
    """A service that is down must not cost the recording."""

    class Broken:
        def shorten(self, lines, language):
            raise RuntimeError("сервис недоступен")

    out, _records, report = shorten_cues(
        long_cues(), "ru", 17.8, Broken(), headroom=1.18
    )
    assert report.failed
    assert out[0].flat_text == long_cues()[0].flat_text
    assert "не выполнено" in report.summary()


def test_lines_that_already_fit_are_not_sent_anywhere():
    """They are the text of the recording, and it does not leave without
    reason."""
    cues = (cue(1, 0.0, 10.0, "Коротко."),)
    provider = FakeProvider([])
    _out, _records, report = shorten_cues(cues, "ru", 17.8, provider)
    assert not report.used
    assert provider.asked == []


# -- the services that can do the rewriting -----------------------------

def test_every_llm_service_is_offered_and_described():
    """A service in the table but not in the list cannot be chosen; one in the
    list but not the table crashes when it is."""
    from lt_core.mt.cloud import LLM_SERVICES, ONLINE_SERVICES

    for key, service in LLM_SERVICES.items():
        assert key in ONLINE_SERVICES, key
        assert service.base_url.startswith("http"), key
        assert service.default_model, key
        assert service.where_to_get_a_key, key


def test_nvidia_is_reachable_over_the_same_protocol():
    """It needed no new code, only an entry: same chat-completions shape."""
    from lt_core.mt.cloud import LLM_SERVICES, build_cloud_provider

    service = LLM_SERVICES["nvidia"]
    assert service.base_url == "https://integrate.api.nvidia.com/v1"
    provider = build_cloud_provider(service="nvidia", api_key="nvapi-test")
    assert not provider.is_offline
    assert can_shorten(provider)


def test_a_hosted_service_is_never_reported_as_offline():
    """«Offline» is a promise about where the words go, not a preference."""
    from lt_core.mt.cloud import build_cloud_provider

    for service in ("openai", "groq", "nvidia"):
        provider = build_cloud_provider(service=service, api_key="test")
        assert not provider.is_offline, service


# -- a slow service costs its own batch, not the recording ---------------

class FlakyProvider:
    """Answers the first request and times out on the rest."""

    shorten_lines_per_request = 2

    def __init__(self) -> None:
        self.calls = 0

    def shorten(self, lines, language):
        self.calls += 1
        if self.calls > 1:
            raise TimeoutError("the read operation timed out")
        return ["Коротко." for _ in lines]


def many_long_cues(count: int = 6):
    """Without a negation in it: the safety check would reject a rewrite that
    dropped one, and this is about what happens to a batch, not to a line."""
    return tuple(
        cue(i + 1, i * 2.0, i * 2.0 + 1.2,
            "Этот довольно длинный текст занимает гораздо больше времени")
        for i in range(count)
    )


def test_a_failed_batch_does_not_discard_the_others():
    """One request timing out used to throw away the whole pass: a recording
    whose 200 over-long lines had been rewritten came out with none of them,
    because the fifth request was slow."""
    provider = FlakyProvider()
    cues = many_long_cues()
    out, _records, report = shorten_cues(
        cues, "ru", 17.8, provider, headroom=1.18
    )
    assert report.accepted == 2, "первая пачка должна была уцелеть"
    assert report.lost == 4
    assert out[0].flat_text == "Коротко."
    assert out[-1].flat_text == cues[-1].flat_text


def test_the_report_says_how_many_were_lost():
    provider = FlakyProvider()
    _out, _records, report = shorten_cues(
        many_long_cues(), "ru", 17.8, provider, headroom=1.18
    )
    summary = report.summary()
    assert "сократила 2" in summary
    assert "без ответа" in summary


def test_everything_failing_still_reads_as_a_failure():
    class Broken:
        shorten_lines_per_request = 2

        def shorten(self, lines, language):
            raise RuntimeError("сервис недоступен")

    _out, _records, report = shorten_cues(
        many_long_cues(), "ru", 17.8, Broken(), headroom=1.18
    )
    assert report.accepted == 0
    assert "не выполнено" in report.summary()


def test_shortening_asks_for_fewer_lines_than_translating():
    """A rewrite is a longer answer than a translation, and a large model on a
    free tier takes seconds a line."""
    from lt_core.mt.cloud import (
        DEFAULT_LINES_PER_REQUEST,
        SHORTEN_LINES_PER_REQUEST,
    )

    assert SHORTEN_LINES_PER_REQUEST < DEFAULT_LINES_PER_REQUEST
