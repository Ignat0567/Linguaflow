# Day 5 — spoken translation (2026-09-17)

Scoped to a time budget. Dubbing is built and verified; the interface is next.

## Built

`lt_core/tts/speaker.py` — a Piper voice, and fitting a line into the slot its
original occupied.
`lt_core/tts/dub.py` — assembling the track, ducking the original, mixing.
Wired into the batch pipeline and the CLI: `--voice`, `--voice-only`.

229 tests.

## Acceptance

47 s of English, recognised, translated and dubbed into Russian in **5.9 s**.
Eleven lines spoken; two did not fit their slot and were allowed to run over;
one was spoken at the compression limit.

Measured on the produced file: 49.2 s, peak 0.980 (no clipping), RMS inside the
cue windows 0.1199 against 0.0123 in the gaps -- the voice is present and the
original sits well underneath it.

## Findings

1. **Piper's `length_scale` is not proportional to duration.** The obvious
   assumption -- ask for 0.9 and get a line 10% shorter -- is wrong. Measured on
   ru_RU-dmitri-medium: 0.909 shortened a 3.32 s line by **1%**, and 0.770 by
   13% rather than 23%. Part of every utterance does not scale: leading and
   trailing silence, and the model's floor on phoneme length. Fitting now works
   from the measured response, and a 3.0 s slot lands at 2.98 s instead of
   3.34 s.
2. **There is a ceiling on fitting, and it is low.** Roughly 15-20% off a line
   before the voice stops sounding like a person. Since Russian runs longer
   than English and German longer still, some lines cannot fit however they are
   asked. They are allowed to overrun and the count is reported, because an
   overlap of a few hundred milliseconds is far less noticeable than a chipmunk.
3. **A line is never stretched to fill a slot.** A dub that drawls through
   silence sounds worse than one that finishes early.
4. **Overrunning lines overlap rather than being cut.** That is what a person
   talking over the end of a sentence sounds like; a line chopped mid-word is
   not.
5. **The original is ducked, not removed.** At -18 dB it is audible enough to
   follow who is speaking and with what emphasis, and it is what a reviewer
   checks against when the numeric audit flags a translation. The duck fades
   over 150 ms: a level step is audible as a click.
6. **Overlapping lines sum past full scale.** The track is normalised down when
   they do, because clipping is audible and unfixable afterwards.

## Not done

The five interface screens, the subtitle overlay, and live streaming speech.
Live speech reuses everything here -- the fitting question does not arise,
since there is no slot to fill -- but it needs the echo gate wired in, which is
the one thing on this list that cannot be tested without a person talking.
