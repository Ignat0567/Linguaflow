# Day 6 — interface (2026-09-17)

The five screens the Day 5 note left outstanding. The pipeline does not
change; this day is the window that calls it.

## Built

`lt_ui/` — Qt window over the existing glass recipe: floating nav, five
screens, a store for settings and history, workers so the GUI thread never
loads a model or waits on a file.
`tools/app.py` — `python tools/app.py`.

245 tests.

## Acceptance

Criterion was: the five screens exist, look like the handoff, and call the
real pipeline rather than the prototype's timers.

Screenshots against the handoff (home, realtime, upload, history, settings)
are in `spike/ui_*.png`. Glass over the photograph, the pill nav, the two
home cards, the record button and the dropzone match.

The window constructs, the nav switches, the language pair refuses a
same-to-same selection, and a settings change survives a restart — all
without loading a model.

## Findings

1. **A wrapping 52px headline collapsed to the word «Что».** QLabel with
   word-wrap, inside a scroll area that resizes its child to the viewport,
   reports a size hint of one wrap opportunity until it has been given a
   width. The layout then assigned that width, and the rest of the title
   had nowhere to go. The headline is one line; screens now declare a
   minimum size so a scroll area cannot shrink them below their content.
2. **The prototype's account block has no counterpart.** There is no
   «Мария Иванова» and no logout. Replaced with the setting the product
   actually turns on: where the text goes. Offline is the default; online
   reveals the service picker. A silent fallback is still impossible.
3. **A three-way voice picker (neutral / male / female) would be a lie.**
   Each language has one Piper voice. The settings page names it
   (Lessac, Dmitri, Thorsten) instead of offering genders we cannot
   produce.
4. **Download chips only offer files the pipeline wrote.** The prototype
   promised «Видео с субтитрами (.mp4)». File mode does not burn captions
   into a container, so that chip is absent. SRT, TXT, bilingual SRT and
   the dubbed WAV appear when they exist.
5. **Live voice still cannot be accepted on this machine without a
   person talking.** The echo gate is wired; the Day 5 limitation stands.
   Subtitle-only live mode does not need it.

## Not done

Packaging into an installer. The five extra languages stay behind
`LINGUAFLOW_LANGUAGES`. The floating caption overlay is in `lt_ui/overlay.py`:
it can be hidden from a full-screen share (Meet, Zoom) via
`WDA_EXCLUDEFROMCAPTURE`; sharing a single application window does not
need the flag, because the overlay is a different window.
