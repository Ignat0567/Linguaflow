# Day 7 — voices that match the speaker, and a dubbed video (2026-09-17)

Two things were asked for: a man should be read out in a male voice and a
woman in a female one, and a translated video should be saved as a copy of
the original with the new soundtrack against the picture.

## Built

`lt_core/audio/pitch.py` — fundamental frequency of a stretch of speech.
`lt_core/tts/casting.py` — which voice reads which line, and the threshold.
`lt_core/tts/speaker.py` — `VoiceBank`: two voices held at once, loaded lazily.
`lt_core/video/mux.py` — a copy of the video with the translated track first,
the original second and the translated subtitles third. Nothing re-encoded
except audio.
Wired through the pipeline, the CLI (`--one-voice`, `--no-video`) and the
settings screen.

293 tests.

## The voices, measured

Piper publishes no gender for its voices, so every candidate for the three
offered languages was synthesised on the same sentence and measured.

| language | male | Hz | female | Hz | apart |
|---|---|---|---|---|---|
| ru | ruslan-medium | 128 | irina-medium | 177 | 49 |
| en | hfc_male-medium | 114 | lessac-medium | 198 | 84 |
| de | thorsten-medium | 131 | ramona-low | 191 | 60 |

Rejected on the measurement: `ru_RU-dmitri` (186 Hz), `en_US-ryan` (161 Hz),
`de_DE-kerstin` (165 Hz), `de_DE-eva_k` (172 Hz).

## Acceptance

A 106-second video with two speakers in it, English to Russian, dubbed and
assembled in **10.6 s** — recognition, translation, twenty spoken lines, two
voices and the video copy.

The result was then measured rather than listened to and trusted:

| | original | dub |
|---|---|---|
| lines 1–11 | 88–99 Hz | 107–151 Hz (ruslan) |
| lines 12–20 | 187–209 Hz | 170–193 Hz (irina) |

Two speakers in, two voices out, 52 Hz apart, and not one line given to the
wrong voice. The threshold the recording produced for itself was 143 Hz,
which falls in the empty band between the two speakers (99 to 187 Hz).

The assembled video: picture copied h264 640x360 25 fps unchanged, audio
track 1 `rus` (default), track 2 `eng`, subtitle track `rus`, duration
105.72 s against the source's 105.72 s. Muxing cost **0.81 s**.

## Findings

1. **Piper's voice names do not tell you the gender, and guessing gets it
   backwards.** The Russian default `dmitri` measures **186 Hz** — inside the
   female range — and `irina` measures **177 Hz**. Pairing those two, which
   is what their names invite, would have produced a "two-voice" dub that
   sounds like one person throughout. Measuring found `ruslan` at 128 Hz
   instead.
2. **The measurement was cross-checked before it was trusted.** Autocorrelation
   and a harmonic product spectrum are independent methods with different
   failure modes; they agreed to within 2 Hz on every voice (dmitri 182/180,
   irina 173/172, ryan 156/151, lessac 195/194). Without that, the surprising
   Russian result would have looked like my own octave error rather than a
   property of the voices.
3. **Pitch in a real recording is bimodal, and the gap is wide.** Measured on
   four recordings: two-speaker files put one cluster at 88–120 Hz and the
   other at 160–240 Hz, with the band between 120 and 160 Hz empty. So the
   threshold is taken from the recording's own gap, and only falls back to a
   fixed 155 Hz when a file holds one speaker — a fixed number would sit in
   the wrong place for an unusually high or low pair.
4. **`-shortest` truncated the video to the subtitle track.** Adding
   subtitles — free, no re-encode, obviously harmless — silently cut **two
   seconds of picture** off a 105.7 s video, because the last caption closed
   at 103.7 s and `-shortest` ends the output when *any* input stream ends.
   Nobody debugging a short video would look in the subtitle track for the
   cause. The picture's own duration is asked for explicitly now, and there
   is a regression test that builds a video whose captions stop at half its
   length.
5. **The picture is copied, never re-encoded.** 0.81 s for a 105-second
   video, and the frames come out identical to the source. Re-encoding would
   have cost minutes per file and quality that cannot be recovered.
6. **The original soundtrack is kept as a second track.** At no cost, since it
   is muxed rather than mixed, and it is what a reviewer switches to when the
   numeric audit flags a line.
7. **`with_suffix` ate the language tag, and nearly the source file.**
   The pipeline names its output `<stem>.<language>` and lets the muxer add
   the container, so `talk.ru` should become `talk.ru.mp4`. `with_suffix`
   treats `.ru` as the suffix and replaces it: `talk.mp4`. Which, since file
   mode writes beside the source by default, is the source video. Found by
   looking at the filename in a real job the user had just run, not by a
   test. The container is appended now, and a destination that resolves to
   the source is refused outright.
8. **A slot-fitted voice is not the speaker's own voice.** The dubbed male
   lines measure 124 Hz where the speaker was at 92. Register is matched;
   identity is not, and no amount of voice choice would change that.

## Limits, stated plainly

- **Register, not sex.** A high-pitched man or a low-pitched woman will be
  given the wrong voice. The decision is per line, so the cost is one line.
- **Two voices, not speaker identification.** Three men in a meeting are one
  voice. Proper diarisation is a different piece of work.
- **German female is a `low`-quality model.** Piper publishes no `medium`
  female German voice; `ramona-low` separates best of what exists.
- **Live and conversation modes still read everything in one voice.** The
  casting needs the original audio for a line, which in a live stream arrives
  as the line is still being spoken. Conversation mode already knows which
  side is talking, so the pair can be wired to the sides there — that is the
  obvious next step and it is not done.
- **A link asked for as a dubbed video downloads the video.** `--no-video`
  keeps the old audio-only download for anyone on a metered connection.

## Also asked for, and built

A light theme, the interface in three languages, and a choice of where
finished files are written.

`lt_ui/theme.py` — two sets of values rather than an inversion.
`lt_ui/i18n.py` — 92 strings in Russian, English and German.
`lt_ui/store.py` — `appearance`, `ui_language`, `output_dir`, all remembered.

321 tests.

### Findings

9. **The light theme is not an inversion of the dark one.** What inverts is
   the text and the scrim; the glass does not, because frosted white over a
   bright photograph is still glass. The thing that made it possible was
   splitting one call in two: the surface colour and the foreground colour
   were both `white()` before, which is exactly the shortcut that makes a
   second theme impossible later.
10. **Panels need six times more white on the light theme.** At the handoff's
   8% a card over a bright photograph reads as a smudge rather than a
   surface. 55% is where it becomes a panel again.
11. **Secondary text had to be lifted.** White at 75% on a photograph reads;
    near-black at 75% on a pale veil looks faded. Every step below primary
    gains 12 percentage points on the light theme, and primary gains none.
12. **A caption translated at import never changes language.** Twice: the nav
    bar kept its Russian captions while every other string switched, and so
    did the online-service list. Both were class or module level constants,
    and both read as correct code. There is now a test that parses every
    module in `lt_ui` and fails on a `_()` call outside a function.
13. **A German interface exposed a layout bug the Russian one hid.** German
    captions are longer, and the toggle rows collapsed onto their own text --
    a scroll area that resizes its child to the viewport takes the extra
    height out of whichever widget reports the smallest minimum, and a
    wrapping label reports nearly none. The rows have a floor now.
14. **The subtitle overlay must ignore the theme.** It does not sit on the
    app's backdrop, it sits over someone else's video call, so its plate
    stays dark and its text stays white. Letting the light theme reach it
    would have put near-black letters on a near-black plate -- caught by
    looking at the rendered window rather than at the code.
15. **`_` cannot be both the translator and the throwaway.**
    `path, _ = QFileDialog.getOpenFileName(...)` makes `_` a local for the
    whole function, and the next argument on the same line was a `_()` call:
    the file dialog raised `UnboundLocalError` before it could open. Python's
    most common idiom and gettext's most common alias collide silently, and
    only when the line runs -- no import fails, no test that does not click
    the button notices. Found because the user clicked it. There is a test
    that refuses `_` as an assignment target anywhere in `lt_ui`.
16. **Changing language rebuilds the screens.** Ninety captions are read from
    the catalogue when their widgets are created, and a person changes
    language once, from a list. Rebuilding is cheaper to reason about than
    ninety `setText` calls, and the models stay loaded.

### Limits

The interface is translated. Progress and error text coming out of
`lt_core` -- «Распознаю», «Собираю субтитры», the translation report -- is
still Russian in all three interfaces, because those strings are formatted
where they are raised rather than where they are shown. Routing them
through the same catalogue is the next step and is not done.

## The translation broke off, and why

Reported from a real 12-minute recording: the translation started correctly
and then fell apart. Measured rather than watched -- translated characters
against original characters, minute by minute:

| minute | 0 | 1–6 | 7 | 8 | 11 |
|---|---|---|---|---|---|
| sentence ends in the transcript | 8 | **0** | 2 | 4 | 4 |
| translated length / original | 0.61 | **0.07–0.16** | 0.14 | 0.53 | 1.03 |

The two rows are the same fact. Whisper punctuated the first minute and then
stopped, and where there are no full stops the sentence splitter had nothing
to split on, so an entire unpunctuated run reached NLLB as one piece.

Measured directly: **6752 characters in, 1025 out**, cut off mid-clause. The
model had written to its own ceiling -- 256 tokens by default -- and stopped.
The tokenizer even printed a warning (1495 > 1024) and nothing in the pipeline
was listening. What the viewer saw was worse than missing text: the surviving
translation was spread thinly across the following three minutes of cues, so
each line carried two or three words about something said minutes earlier.

### The fix, in two parts

17. **A run with no punctuation is cut at clause boundaries.** Commas first,
    since a clause is a real boundary and translates as one; only a clause
    that is itself too long is cut between words, which is a bad place to cut
    and better than losing the rest. `MAX_WORDS = 40` is measured against the
    model's writing ceiling, not chosen for style.
18. **A translation far shorter than its original is reported.** `SHORT_RATIO
    = 0.5`: among these languages a translation is never much shorter than
    what it came from -- Russian runs longer than English, German longer
    still. Half is nowhere near any working pair and is exactly what a cut-off
    one looks like. Applied only above a dozen words, where the ratio means
    something.

Re-run over the same recording, every minute now lands between 0.89 and 1.11
against 0.07–0.16 before. With the splitting disabled again, the new check
reports «ПЕРЕВОД ОБОРВАН в 1» instead of saying nothing.

337 tests.

### Why it stopped punctuating

Answered afterwards, by measurement rather than reasoning. Four hypotheses
were tested on the same 120-second stretch that had produced one sentence end
in 2227 characters:

| | sentence ends |
|---|---|
| as shipped (VAD on, no context) | 1 |
| `condition_on_previous_text=True` | 0 |
| `vad_filter=False` | 1 |
| both | 0 |

So neither the voice-activity filter nor carrying context was the cause, and
the first two guesses were wrong. What worked was priming the model with a
short, properly punctuated sample: **13** sentence ends. Prompt *and* context
together: **31**. The model copies the style of whatever it is started with,
and started with nothing it transcribes fast continuous speech as one run.

Over the whole 12-minute recording:

| | sentence ends | capitals | characters |
|---|---|---|---|
| as shipped | 23 | 54 | 13920 |
| + punctuated sample | 37 | 90 | 13958 |
| + sample and context | **184** | **279** | 14111 |

19. **The sample is written in each language.** A prompt in the wrong language
    is the one way this is known to do harm -- it is what turned a German turn
    into Russian on Day 4 -- so the language is settled first, from the opening
    seconds, and the matching sample chosen. English text primed onto a German
    clip did no harm when tried, but that is not a reason to rely on it.
20. **Carrying context was off for a good reason, and the reason cost more
    than it saved.** The concern -- one bad transcription poisoning everything
    after it -- is a real failure mode. Measured across three recordings, no
    repetition appeared, and the lengths moved by -0.5%, +1.4% and +25%. It is
    on for file mode and stays off for the live path, where a window is two
    seconds and its context is already supplied as committed words.
21. **The guard against that risk cut real speech, so it is not used.**
    `hallucination_silence_threshold=2.0` looked like the right insurance and
    removed 111 characters of a genuine sentence from a two-person recording
    -- "released four major functions and significantly reduced the average
    response time" vanished between one clause and the next. A guard against
    silent loss that causes silent loss is not a guard.

Downstream, on the recording that started this: punctuation in every minute
(9-20 marks against none for minutes 1-6), translated length 0.90-1.05 of the
original throughout, and 243 subtitles instead of 189 -- because the cue
splitter can finally break at real sentence ends rather than mid-thought.

354 tests.

## Making the translation fit the slot

Asked for after listening to the dub: shorten the translation by meaning so
that it can be spoken in the time the original took.

First, the size of the problem, measured rather than estimated. Of 243 lines,
101 could not be spoken in their slot even at the voice's speed limit -- and
the median one overran by only **1.13x**. Eleven per cent, on the median line.
That is the whole of what has to go.

### Built

`lt_core/mt/condense.py` — the rules, and the slot arithmetic.
`lt_core/mt/shorten_with_model.py` — the rest, handed to the model.
Wired ahead of the subtitles, so that what is on screen is what is said.

### Findings

22. **A line may use the silence before the next one.** A cue ends when its
    words end, not when the next begins. Counting the slot to the *start of
    the next line* took the lines that do not fit from 75 to 59, changed no
    text at all, and cost nothing.
23. **The budget belongs to the voice, not to the language.** Measured:
    ruslan says 18.4 characters a second and irina 13.9 -- a third apart. One
    number for both would have been wrong by that much for one of them. The
    fuller model is `duration = 0.19 s + characters / 17.8`; the fixed part is
    the silence at the edges, which does not scale.
24. **Commas cost almost nothing.** Worth checking, since the punctuation fix
    had just multiplied them eightfold: 17.2 characters a second without them
    against 16.9 with, on the same sentence.
25. **Substituting a noun does not work in an inflected language.** The first
    rule table replaced «программное обеспечение» with «программа» and
    produced **«открыть программа»** -- the replacement arrived in the
    nominative and the sentence wanted the accusative. A line that runs over
    is a smaller fault than a line in the wrong case, so every rule that
    agrees with its surroundings was taken back out. What is left are
    conjunctions, adverbials, whole predicates, and two quantifiers that
    govern the same case as what they replace.
26. **Rules cannot reach eleven per cent, and the measurement says why.**
    Machine-translated prose has almost no filler in it: the rules could touch
    19 lines in 243. Removing a tenth of a sentence that contains no filler is
    rewriting, not deletion.
27. **So the rest goes to the model that did the translating** -- and only
    when the user is already working online, because it is the same text going
    to the same third party and no further. In offline mode nothing is sent,
    which is the promise the mode exists to make.
28. **Everything the model returns is checked before it is used.** A line that
    lost a figure, gained or lost a negation, came back empty, or came back
    longer is discarded and the original kept. Running over is a smaller fault
    than saying something else, and a model asked to be brief will cheerfully
    drop a «не».

### What it is worth

Offline, on the recording that prompted this: lines that overran their slot
went from **104 to 91**, and lines spoken at the compression limit from 138 to
122. Nothing was lost to get there -- 10 lines had filler removed, 106
characters in total, and the rest of the gain is the silence between lines.

That is honest progress and not a solution. The remaining 91 need a tenth of
their words rewritten away, which the model path does and which needs a key
and online mode turned on. It has been tested against a stand-in provider, not
against a live service.

### Where the rewriting can be done

NVIDIA's catalogue speaks the same chat-completions protocol, so it is one
entry in the table rather than any new code, and it comes with free credits.

Checked as far as it can be without a key: the endpoint parses a request and
answers with a structured error, the model list is public and returns 82
models, and a bad key comes back 403 -- which the existing code already
reports as «сервис отклонил ключ». The generation itself is not verified.

The obvious default was already dead: `meta/llama-3.3-70b-instruct` reached
end of life on 2026-08-26 and the endpoint said so. The catalogue moves, so
`--llm-model` takes any id from `integrate.api.nvidia.com/v1/models`.

### With a key, measured

A free NVIDIA key opens a small part of the catalogue -- six of the 57 chat
models answered for this account -- and picking a default by name would have
failed three times over:

| | |
|---|---|
| `meta/llama-3.3-70b-instruct` | retired 2026-08-26, the endpoint said so |
| `mistralai/mistral-large-2-instruct` | 404, not enabled for the account |
| `nvidia/nemotron-3.*` | answer with their reasoning out loud |
| `nvidia/ising-calibration-1.5-31b` | shortened 0 of 18: every answer failed a check |
| **`google/gemma-4-31b-it`** | **shortened 15 of 18, clean Russian** |

29. **Which model shortens is a separate choice from which model
    translates.** Running the whole recording through a 31-billion-parameter
    model on a free tier meant 3-5 seconds a line and about twenty minutes,
    where the local translator does it in four seconds and does it well. Only
    the lines that do not fit need rewriting, so `--shorten-with` sends those
    and nothing else, and the translation stays on this machine.
30. **A character budget cannot stand in for the synthesiser.** Fitted to two
    probes it said 17 lines were too long where the voice then overran on 86
    -- short lines are spoken more slowly per character than long ones, and no
    single rate describes both. The budget is now taken from synthesising the
    line and measuring it, which costs one extra pass over a fast model and
    removes the error.
31. **The timeout was a Groq number.** Sixty seconds, where Groq answers in
    about one. A large model on a free tier took longer and the whole
    recording was lost at the last step; waiting longer costs nothing when the
    service is quick.

### What it is worth, end to end

On the recording that prompted all of this, 243 lines:

| | overran their slot | at the speed limit |
|---|---|---|
| before any of this | 104 | 138 |
| clause slots and rules, offline | 91 | 122 |
| measured budgets and the model | **56** | **83** |

57 lines were shortened, 1231 characters removed, and 8 of the model's answers
were refused by the checks and the originals kept. The model added about two
minutes to a 214-second run.

Fifty-six lines still overrun. The checks accept any answer that is shorter
and safe, including one that is shorter but still over its budget, which is an
improvement rather than a fix and is counted honestly as such.

384 tests.

## Ready to be installed

The program is to be shipped as an installer, which changes where a user's
own things belong.

32. **A key is the user's, not the program's.** Settings has a field for it,
    and it is kept apart from `settings.json` -- which is rewritten on every
    toggle and travels with a copied folder. On Windows it is sealed with
    DPAPI, the operating system's per-user protection: no password, no
    dependency, and a folder copied to another account will not open it.
    Measured: a 17-byte key becomes a 246-byte blob with no trace of the key
    in it, and a blob from elsewhere is refused. Where there is no such
    facility the file is plain text, and the interface says so rather than
    implying otherwise.
33. **The Test button asks the service a real question.** Verified against the
    live endpoint: a working key answers «ключ работает», a wrong one «сервис
    отклонил ключ доступа». An empty field is answered before any request,
    because the provider's own refusal names `--api-key` and an environment
    variable -- the command line talking inside a window that has a field for
    exactly this.
34. **User data moved out of the program's folder.** `Program Files` is not
    writable, and one settings file shared by everyone who signs in is the
    wrong shape for someone's languages, history and key. Settings, history
    and keys now live in `%APPDATA%\Linguaflow`, with the platform's
    equivalents elsewhere and `LINGUAFLOW_DATA` for a portable copy.
35. **Two things deliberately stayed behind.** Models, because they are
    gigabytes, identical for every user and read-only in use; and finished
    files, because they go wherever the user chose, which is the point of that
    setting.
36. **The migration copies and does not move.** State is carried across only
    when the new place does not have it, the old folder is left intact, and
    job outputs stay where they are -- the history names them by absolute
    path, so they keep working, and moving gigabytes of audio is a poor way
    to spend a first start. Run against the real profile: 24 settings, 5
    history entries and the key arrived; four job folders and every file they
    point at stayed where they were.

37. **Two-means will split anything, including one person.** A five-minute
    talk by one man came back with 16 of its 74 lines read by a woman. The
    guard was "the clusters are far enough apart", which two-means satisfies
    on any list of numbers. The guard that works is an *empty band*: measured
    across every recording on hand, genuine pairs leave 63-88 Hz of the scale
    untouched, one speaker leaves 0.2-2.0 Hz. And when a recording holds one
    speaker, the fallback threshold now picks the voice for the recording
    instead of being applied line by line -- his own pitch ran 115 to 231 Hz,
    so a line-by-line comparison against any fixed number changes voices.
38. **Ducking followed the subtitle, and the subtitle outlives the line.** A
    translated line is usually shorter than the line it translates, so the
    original stayed 18 dB down after the dub had stopped speaking. Measured on
    that same file: **111 stretches, 77.5 s of a 297 s video, the longest 8.0
    s**, with nothing audible in them at all -- which is what the person
    watching reported as "gaps". Ducking now follows the utterances the dub
    actually produced: 12.2 s remain and the longest is 0.65 s, every one of
    them inside the deliberate 0.7 s bridge that stops the level pumping
    between two sentences.
39. **A cue boundary fell inside a word.** Whisper emits "self-improvement" as
    " self" and "-improvement,", and the missing leading space is the only
    thing that says they are one word. `_join` honours that -- it is why
    "$12,000" survives -- and `_best_break` did not, so the viewer read "...a
    policy of self" and then "-improvement, self-change."
40. **Priming the second pass with the first pass's own words was measured and
    dropped.** The recogniser heard "coordination" as "coronation" four times
    in the first four minutes, correctly seven times later. A second pass
    primed with sentences from the first fixed all four and fixed the garbled
    closing line -- and turned "loss of face" into "loss of faith" twice and
    digits into spelled-out numerals. `avg_logprob` does not tell the two
    apart: it preferred "coronation" in two of the four places and rated the
    primed pass worse overall. A change that trades one class of error for
    another with no way to tell which is which is not an improvement.

41. **A live commit boundary made of seconds loses words and repeats them.**
    The buffer is trimmed after every commit and the model re-estimates every
    word's timing on the shorter audio, so a word that was never committed
    comes back ending a fraction before the boundary and vanishes -- measured
    in the first four hundred characters of a real talk: "the people who always
    win" became "the who always win", "which is the ability of these people"
    became "which is the of these people", and the same movement the other way
    gave "they They win" and "times times energy". The boundary is now the
    repetition itself: the buffer deliberately keeps a few seconds of committed
    audio for context, so a hypothesis opens by re-transcribing the tail of
    what is committed, and that is what to cut on. Where the trim leaves
    nothing to align against, the word the hypothesis opens with is the word
    the agreement was already waiting for. Forced commits fell from 21 to 5,
    and "не весят одинаково" stopped arriving as "весят одинаково".
42. **Waiting for a full stop is right, and asking for it at the end of the
    accumulation is not.** A sentence that finished mid-commit sat unread until
    a later commit happened to land exactly on one: first translation at 40 s,
    a median of 10 s between them, one of 496 characters. Finished sentences
    now go on their own.
43. **The unfinished sentence is translated too, and marked as provisional.**
    Cutting the *committed* translation at clauses was measured first and costs
    meaning: "mass times energy times coordination", handed over a clause at a
    time, comes back as "масса во время энергии", because "times" without its
    sentence is the preposition. So the committed text stays whole-sentence and
    a draft carries the reading -- first text on screen at 4 s instead of 40,
    replaced 118 times over five minutes, for 0.27 -> 0.34 of real time.
44. **In a conversation, which alphabet the words came out in beats which
    window the audio fell in.** Committed text trails the audio by seconds, so
    at a handover the window has already changed hands while the words still
    belong to whoever was talking: "four major features." went to the Russian
    side and "За последние три месяца." to the English one, and the translator
    returned both unchanged. One commit can also hold both at once, and is now
    split. Where the two sides share an alphabet -- English and German -- this
    stays silent and the audio is still all there is.
45. **Conversation mode sent no prompt at all, and threw away its own
    ending.** No prompt was right for the previous speaker's words and wrong
    for the punctuated sample, which is nobody's words; without it the Russian
    side barely punctuated, so its turns never finished and never got
    translated. And the window feeds chunks itself so that it can stop on a
    button, then asked for the tail only `if isinstance(session, LiveSession)`
    -- so the last thing either person said was dropped every time. Measured on
    a two-language dialogue: turns returned untranslated 2 of 9 -> 0 of 12,
    first reading 6.1 s -> 4.1 s, median gap between readings 6.1 s -> 2.0 s.

46. **A translated cue stopped ending on the word that governs the next one.**
    Splitting a translated sentence across the cues its source occupied was
    done purely by proportion, and arithmetic knows nothing about phrases:
    measured on an hour of real output, 42 of 1462 Russian cues ended on a
    preposition or conjunction — "…умноженное на", and then, a cue later,
    "энергию". The source language had avoided this since Day 2. The split may
    now move by up to two words onto a clause end, or failing that off a
    clinging word. On the five-minute file: 4 such cues before, 0 after.
47. **Routing a conversation by when each word was said was built, measured
    and dropped.** Where the two sides share an alphabet — English and German —
    the letters cannot say who is talking, so the audio window's verdict is all
    there is, and a commit that straddles a handover is attributed wholesale to
    whoever is speaking by the time it settles. The fix tried was a timeline of
    per-window verdicts, with each committed word looked up by its own
    timestamp. Measured on a 47-second English/German dialogue against an
    oracle that reads the text itself: **76% of runs attributed correctly
    before, 77% after**, and no change at all on the Russian/English pair,
    where the alphabet already decides. It splits handovers into more runs
    without making them more often right, because it reads back the same
    per-window verdicts that were wrong to begin with — shifting when they are
    consulted does not make them true.

    What a same-alphabet pair actually needs is voice identity rather than
    language identity. The pitch of each side is already pooled for choosing
    its voice, so the signal is in hand; using it to decide *who is speaking*
    is diarisation-lite and a larger piece of work than this was. Left
    undone deliberately, and measured so that it is not built again by
    accident.

553 tests.

## Not done

Packaging into an installer. Burning subtitles into the picture (they are
embedded as a selectable track, not painted on). The five extra languages
stay behind `LINGUAFLOW_LANGUAGES`, and none of them has a measured voice
pair.
