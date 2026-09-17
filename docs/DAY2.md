# Day 2 — file mode (2026-09-17)

## Built

`lt_core/asr/` — faster-whisper behind a small interface, with word-level
timings, real progress reporting, and hallucination filtering.
`lt_core/subtitles/` — cue construction and export to SRT, WebVTT, TXT and JSON.
`lt_core/media.py` — local files and URLs (yt-dlp), duration probing.
`lt_core/pipeline/batch.py` — the whole of file mode as one callable.
`tools/transcribe.py` — the command line.

89 tests, all passing. The four regression tests below were verified by
mutation: each was confirmed to fail when its bug is reintroduced.

## Acceptance

Criterion was: a long recording produces a correct SRT in reasonable time.

A 7 min 33 s lecture (AAC in an .m4a container, twenty distinct passages in two
voices) transcribed in **12.7 s -- 36x faster than real time**, producing 111
cues from 1194 words.

Structural validation of the SRT: 111 blocks, zero malformed, zero overlapping,
zero with non-positive duration, zero lines over 42 characters, never more than
two lines per cue.

Content validation against the known source: the opening paragraph matched word
for word, and all twelve checked figures survived -- 420 ms, 290 ms, 3.1 s,
1.4 s, 99th percentile, 11 weeks, 9 incidents, $12,000, 40 minutes, 11 days.

Whisper normalises spelled-out numerals to digits ("four hundred and twenty" ->
"420"), which is correct for subtitles. The first version of this check looked
for the spoken form and reported everything as missing; the check was wrong,
not the transcript.

## Findings

1. **Whisper's segment boundaries are not speech boundaries.** They are cut by
   its thirty-second decoding window. On the reference clip five of eight
   segments ended mid-phrase -- on "per", "our", "of", "a", "the" -- each with
   a gap of exactly 0.00 s to the next. Building cues per segment stamps every
   one of those into the subtitles. Cues are now built from a continuous word
   stream and divided where the audio actually goes quiet.
2. **Re-joining words with a uniform space corrupts text.** Whisper's tokens
   carry their own leading whitespace and its absence is meaningful: "$12" is
   followed by ",000", "real" by "-time". Stripping and re-joining produced
   "$12 ,000" and "real -time" in every exported file.
3. **Fixed-width line breaking splits numbers in CJK.** "31%" became "3" at the
   end of one line and "1%" at the start of the next -- the same corruption as
   above, one layer further on, where the text was right and the line break
   destroyed it. Chinese and Japanese now break on atomic units, balanced, and
   preferring punctuation.
4. **CJK needs its own subtitle metrics, not translated ones.** A 42-character
   Chinese line holds roughly three times the content of a Latin one. The
   limits are 16 characters and 9 cps rather than 42 and 17.
5. **A fragment alone on screen reads as a stutter.** A real half-second pause
   correctly ends a cue, but can leave "Guten Morgen," flashing by itself while
   its sentence follows separately. Runts are merged where the combined cue
   still fits every limit and the gap is under a second.
6. **Ending a cue on a preposition reads as a stumble.** "...by roughly $12,000
   per / month" -- the break point now steps back off articles, prepositions
   and conjunctions in all six space-separated languages.
7. **The model loaded before the source was checked.** A mistyped URL cost two
   seconds and two gigabytes of VRAM before the error appeared. Resolution now
   happens first.

## Known limitation

Without a word segmenter, a Chinese or Japanese line break can still fall
inside a two-character word. Adding one (jieba, fugashi) is a dependency and a
dictionary; splitting a number in half was the serious half of this problem and
it is fixed.
