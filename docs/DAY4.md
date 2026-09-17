# Day 4 — live translation (2026-09-17)

## Built

`lt_core/realtime/agreement.py` — LocalAgreement: a word is committed once two
consecutive hypotheses agree on it, and committed text never changes again.
`lt_core/realtime/session.py` — the streaming session: rolling buffer, pacing,
incremental translation, bounded memory.
`lt_core/realtime/conversation.py` — two people, two languages, one microphone.
`tools/live.py` — microphone, system audio, or a recording replayed at
wall-clock speed.

191 tests. Two Day 4 regressions verified by mutation.

## Acceptance

Criterion was: fifteen minutes of continuous speech without drift or leak.

**Passed.** 906 seconds of audio in 906 seconds of wall time:

| | |
|---|---|
| lag | median **2.3 s**, p95 4.3 s, worst 5.0 s |
| drift | first half 2.3 s, second half 2.3 s — none |
| memory | 1.6 → 2.0 MB, peak 13 MB — no leak |
| buffer | never above 10.0 s |
| load | 0.45 of real time |

## The pacing dial

Measured on the reference clip, against the same file transcribed in batch:

| pace | promised | median | p95 | worst | accuracy |
|---|---|---|---|---|---|
| fast | 2.9 s | 1.7 s | 2.7 s | 2.9 s | 94.2% |
| balanced | 4.9 s | 2.3 s | 4.1 s | 4.2 s | 97.3% |
| steady | 8.9 s | 4.2 s | 4.7 s | 5.6 s | 95.0% |

`steady` is dominated by `balanced` on this clip -- slower *and* less accurate.
One clip is not enough to drop it, but it is not the default and it is not
recommended.

## Findings

1. **One unstable word blocked the entire stream for fourteen seconds.**
   Agreement confirms a prefix, so a word the model will not settle on stops
   everything behind it. The model rendered "31%" differently on every pass;
   the commit point stood at 12.0 s while the buffer grew to 18.6 s, and it
   resolved only by luck. Now the prefix is accepted without a second opinion
   once the lag exceeds a bound: worst-case lag fell from 15 s to 2.9 s, buffer
   from 18.6 s to 7.0 s, with the same number of words transcribed.
2. **The escape hatch's first trigger almost never fired.** It asked "how long
   since anything committed", and a single trailing word agreeing advanced the
   commit point by hundredths of a second and reset the timer while the stream
   stood still behind it. Measured as a lag instead, which is what actually
   needs bounding.
3. **The promised latency was wrong by a whole window.** `window + 0.85`
   ignored that a word cannot be committed on the tick it first appears --
   agreement needs a second hypothesis, a window later. Now `2 × window + 0.9`,
   which measurement confirms as a conservative upper bound.
4. **Forgetting history moved the commit point backwards.** Deriving it from
   the retained word list meant that trimming history let audio already
   transcribed be accepted a second time. The commit point is now tracked
   separately and never regresses.
5. **Context conditioning fights speaker switching.** Feeding committed text
   back as a prompt is what makes a live transcript read as prose -- and in a
   two-language conversation the prompt is in the *previous* speaker's
   language, dragging the model into transcribing the next speaker in it too. A
   German turn came out as Russian, and the translation of that degenerated
   into "The system." repeated five times. Off in conversation mode.
6. **Language detection was not the weak point, contrary to the hypothesis.**
   Measured on one-second windows: en 0.99, ru 1.00, de 1.00. Restricting the
   choice to the two configured languages is still worth it -- a window holding
   neither scores near zero for both, which is usable information -- but the
   corruption above came from the prompt, not from detection.
7. **A pause scored as a language change.** Restricted detection returned
   "ru 0.21" for a breath inside an English turn, and treating that as a
   speaker switch relabelled the sentence around it. One weak window now
   changes nothing; only a run of three is taken as evidence.
8. **The reported latency had no defensible meaning.** It added the tick's
   compute time to the commit lag and produced 43 seconds on a session whose
   buffer never exceeded 6. Replaced with the plain distance between two
   clocks, reported as median and worst.
9. **"Words transcribed" reported the rolling window.** The committed-word list
   is trimmed to bound memory, so reading its length understated a
   fifteen-minute session by more than half. Counted properly now.
10. **Conversation mode translated fragments.** Each commit went to the
    translator as it landed -- "shipped" came back as "отгруженные", "and thank
    you" as "И спасибо .". This is the Day 3 finding reappearing one layer up.
    Text is now held until a sentence finishes or the turn changes.
11. **A released sentence was labelled with the wrong speaker.** When a turn
    changed, the previous speaker's unfinished sentence was translated and
    attached to the incoming speaker's update -- Russian text under an English
    speaker's name. `feed()` now returns every update it produced rather than
    one.

## Known limitations

**Conversation mode lags at the handover.** Median 2.3 s, but up to 14 s around
a speaker change: the model is still pinned to the previous language, produces
words nobody agrees with, and the stream briefly falls behind. It recovers on
its own. Steady-state attribution is correct.

**Conversation mode costs an extra ~0.32 s per tick** for language detection,
which at `fast` pace is enough to fall behind on this hardware (0.75 of real
time, and it lost 12 s over 105 s). `balanced` or slower is required.

**It cannot separate two people speaking the same language.** Attribution is by
language, not by voice. Telling two voices apart needs diarisation -- another
model, and several seconds of audio before it can decide anything.

**An early mistake is permanent.** That is the deal LocalAgreement makes:
committed text never changes, so text that was committed wrongly stays wrong.
The alternative is subtitles that rewrite themselves under the reader.
