# Day 3 — translation (2026-09-17)

## Built

`lt_core/mt/` — the translation layer: an offline provider (NLLB-200 through
CTranslate2), two online providers (DeepL and any OpenAI-compatible endpoint),
a glossary, and a numeric audit.
`lt_core/subtitles/bilingual.py` — sentence grouping, redistribution, merged
bilingual cues.
Wired into the batch pipeline and the CLI: `--to`, `--mode`, `--glossary`,
`--bilingual`.

158 tests. The three regression tests below were verified by mutation.

## Acceptance

Criterion was: bilingual SRT across pairs, both modes reachable.

Four pairs produced bilingual subtitles: en→ru, ru→de, de→ru, en→zh.

The 7 min 33 s lecture was transcribed **and** translated in 15.5 s. Translation
added 2.1 s to a 13.4 s transcription; 32 of 69 sentences came from cache.

Numeric fidelity over the whole translated lecture: 25 content numbers in the
English subtitles, 25 in the Russian, identical sets. Nothing lost, nothing
invented.

Mode is explicit and never falls back. Offline is the default; asking for it
and silently getting a cloud call would break the only promise that matters
about where a user's words go.

## Findings

1. **Placeholder protection for numbers does not work, and was abandoned after
   measuring it.** Seven placeholder formats were tried across seven target
   languages: the best (`<0>`) survived five, and the two it failed were
   Chinese and Japanese — exactly where the corruption happens. The model
   rewrites anything that does not look like language. Numbers therefore travel
   unprotected and are **audited afterwards**, which cannot repair a
   mistranslation but turns two hundred unverifiable cues into the two or three
   worth looking at.
2. **Digits survive far better than spelled-out numerals**, and Whisper already
   normalises "four hundred and twenty" to "420". That single fact removes most
   of the risk the Day 0 spike found. What remains: en→zh rendered "4.7 million
   dollars" as 47万美元 — 470,000, a factor of ten — and en→ja turned "420
   milliseconds to 290" into "290秒", changing the unit.
3. **The audit was blind in Chinese.** The number pattern used a `\w`
   lookbehind, and `\w` matches CJK, so `削减了12,000美元` matched nothing. An
   audit that cannot see the numbers it is auditing reports success on
   corrupted text — the worst possible failure for a safety check.
4. **transformers recommends a flag that destroys this model.** It warns that
   without `fix_mistral_regex=True` "this will lead to incorrect tokenization".
   Measured over eight sentences: six outputs changed, several into degenerate
   repetition — "We went from roughly 9 incidents a month to 2" became "Мы
   перешли от происшествий, происшествий, происшествий, происшествий" — and
   numbers vanished outright. The warning concerns Mistral tokenizers; acting
   on it here would delete the very figures the audit exists to protect. Flag
   off, warning silenced, reasoning recorded in the code.
5. **Sentence splitting was a no-op for Chinese and Japanese.** The whole point
   of splitting is that NLLB drops sentences from multi-sentence input — the
   Day 0 finding. The pattern required whitespace after the terminator, and CJK
   writes 。flush against the next sentence, so the protection was absent
   exactly where the problem was first observed.
6. **NLLB answers short inputs with invented dialogue.** It was trained heavily
   on subtitle corpora, where a short line is a dialogue turn with a leading
   dash. Measured on seven one-word inputs: a dash in 7/7 Russian and 6/7
   German outputs, two with the sentence repeated, and worse —
   `"Yes." → "Нет, нет."` (the opposite) and `"Hello." → "Ich hab's dir
   gesagt."` (unrelated).
   Three responses: the dashes and repetitions are stripped; whole sentences
   are sent instead of cue fragments, which removes most short inputs
   altogether (11 fragments became 5 sentences on the reference clip); and what
   is still genuinely one word is flagged for review, because it cannot be
   fixed.
7. **Translating cue by cue was the wrong granularity.** A cue is cut for
   reading speed and is routinely half a sentence. Sentences are now grouped
   across cues, translated whole, and redistributed across the original
   timings, which do not move — the words were spoken when they were spoken.
8. **Translated text is longer than its source**, so a cue laid out for English
   overflows in Russian or German. Lines are balanced across however many are
   needed rather than filled greedily, which was leaving one short word
   stranded on a third line.
9. **Duplicate lines were translated once per occurrence.** One sentence often
   spans several cues and speakers repeat themselves; the lecture run reused 32
   of 69 translations.

## Known limitations

A genuinely one-word utterance translated offline is unreliable, and is flagged
rather than fixed. Online mode does not have this problem.

Redistributing a translated sentence across the cues its source occupied is
proportional, not aligned — word order differs between languages, so a cue may
lead or lag its speech slightly. Nothing is lost, and the alternative would be
word alignment, which is a project of its own.
