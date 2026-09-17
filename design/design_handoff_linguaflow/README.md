# Handoff: Linguaflow — Audio/Video Translation App

## Overview
Linguaflow is a desktop web app for translating speech and media across 8 languages (RU, EN, DE, ZH, JA, ES, IT, FR). It supports three real-time modes (live subtitles, subtitled+voiced translation, two-person conversation mode) plus upload-and-translate for video/audio/song files, a translation history log, and settings.

## About the Design Files
The files in this bundle are **design references built as an HTML/JS prototype** — they demonstrate intended look, layout, and interaction, not production code to copy directly. The task is to **recreate this design in the target codebase's existing environment** (React, Vue, native, etc.), using its established component patterns, state management, and libraries. If no environment exists yet, choose the framework best suited to the project and implement the design there.

## Fidelity
**High-fidelity.** Colors, typography, spacing, and interaction states shown are final-intent. Recreate pixel-close using the target codebase's own styling system (CSS-in-JS, Tailwind, native styling, etc.) rather than copying inline styles verbatim.

## Visual Language
- **Aesthetic**: "Liquid glass" — frosted, translucent panels (backdrop blur + saturation) floating over a full-bleed background photo/illustration, in the style of Apple's glass UI treatments.
- **Background**: a single full-bleed image (`assets/bg-translate.png`, 1792×1008) depicting a glowing blue/purple network with floating language-tag bubbles (EN/ES/中文/FR/DE/JA/RU) over a city + globe motif. It sits fixed behind all screens with a dark gradient scrim on top (`linear-gradient(180deg, rgba(4,6,14,0.55) 0%, rgba(4,6,14,0.72) 55%, rgba(4,6,14,0.88) 100%)`) for text contrast. Position tuned so the language bubbles peek out just above/behind the home screen's two glass cards (`background-size: 145% auto; background-position: center 130px;`).
- **Glass surface recipe** (reusable token — apply to every card/panel/button):
  - `background: rgba(255,255,255,0.07–0.10)`
  - `backdrop-filter: blur(20–28px) saturate(160–180%)` (+ `-webkit-backdrop-filter` for Safari)
  - `border: 1px solid rgba(255,255,255,0.16–0.22)`
  - `box-shadow: inset 0 1px 0 rgba(255,255,255,0.25–0.35), 0 8–12px 32–40px rgba(0,0,0,0.3–0.35)`
  - Corner radius: 18–24px for panels/cards, 999px (full pill) for nav, buttons, chips, toggles.
- **Typography**: System font stack for an Apple-like feel — `-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', 'Inter', Helvetica, Arial, sans-serif`. Headlines use weight 700 with tight tracking (`letter-spacing: -0.02em to -0.03em`). Body copy uses weight 400–500. Small uppercase labels (section eyebrows, badges) use `font-size: 10.5–11px`, `letter-spacing: .06–.12em`, `text-transform: uppercase`.
- **Color**: Near-black base (`#04060c` / `#0d0f1a`), all foreground surfaces are white-on-glass (`rgba(255,255,255,*)` at varying opacity for hierarchy: 100% primary text, ~75% secondary, ~55–65% tertiary/meta). One tweakable **accent color** (default `#7fa4ff`, a soft blue) drives active states, the primary CTA card, progress rings, and toggle "on" states — alternate accent options: `#b98cff` (purple), `#5ee6c9` (teal), `#ff9d7a` (coral).
- **Layout model**: no sidebar. A single floating pill-shaped nav bar is centered at the top of every screen; content below it is centered, max-width ~1080px, and each screen picks its own composition (grid, centered stack, or timeline) rather than a fixed dashboard shell.

## Screens / Views

### 1. Главная / Home
**Purpose**: Entry point — pick a mode or jump back into a recent translation.
**Layout**: Centered column, max-width 640px hero, then two glass cards side by side (flex-wrap, each `flex: 1 1 420px`, min-height 210px), then a horizontally scrollable row of up to 3 "recent" cards (`flex: 0 0 220px`).
**Components**:
- H1 "Что переводим сегодня?" — 52px/700/-0.03em.
- Subtitle, 14.5px, 75% white.
- Card 1 (accent-filled glass, gradient `linear-gradient(135deg, accent55, rgba(255,255,255,0.10))`): eyebrow "01 · LIVE", title "Перевод в реальном времени" (29px/700), description, "Начать →" — routes to Realtime screen.
- Card 2 (neutral glass): eyebrow "02 · FILE", title "Загрузка файла", description, "Загрузить →" — routes to Upload screen.
- "Последние переводы" section header + "Все →" link to History.
- Recent cards: type pill label (color = accent for realtime, 60% white for file), title, dashed divider, from→to + duration row.

### 2. Реальное время / Realtime translation
**Purpose**: Live speech translation with 3 sub-modes.
**Layout**: Fully centered vertical stack.
**Components**:
- Top row of two glass pill controls: (a) from/to language `<select>` pair with a swap (⇄) button between them, (b) 3-way mode switch — **Субтитры** (live captions only) / **Текст + озвучка** (captions + implied TTS) / **Разговор** (2-person alternating captions, left/right aligned by speaker).
- Circular record button (96px, glass when idle, filled accent when recording) with two expanding ring pulses (`@keyframes ring`, 1.8s, staggered 0.6s) while active.
- Status caption below the button: "Нажмите, чтобы начать запись" / "Слушаю…" / "Остановлено".
- Glass transcript panel (24px radius, 32px padding, min-height 200px): shows original text (large, 25px/600) + translated text (15px, 72% white) per utterance, revealed one at a time every ~1.8s while recording (demo simulation — in production this streams from the speech/translation pipeline). Empty state: "Нажмите на кнопку, чтобы начать". In conversation mode, entries alternate left/right with a speaker label ("<Language> · A/B").
- After stopping, two secondary glass pill buttons appear: "Сохранить транскрипт", "Скачать аудио перевода".

### 3. Загрузка / Upload & processing
**Purpose**: Translate a pre-recorded video/audio/song file.
**Three states** (idle → processing → done):
- **Idle**: large dashed glass dropzone, max-width 560px, "Перетащите файл" (36px/700) + accepted formats + filled accent CTA "Загрузить демо-файл" (click triggers the demo simulation — production wraps a real file input / drag-drop).
- **Processing**: circular progress ring (`conic-gradient(accent {progress}%, rgba(255,255,255,0.15) 0)`, 160px) with a translucent glass center showing the live percentage; status label cycles "Распознавание речи…" (0–40%) → "Перевод текста…" (40–80%) → "Финализация…" (80–100%); file name shown below, muted.
- **Done**: glass results panel (max-width 760px): file header (name, size/duration, language pair) + "Другой файл" reset link; per-line transcript grid (`52px timestamp column | text column`, original bold + translation muted); download row of glass pill chips: Субтитры (.srt), Текстовая расшифровка (.txt), Переведённая аудиодорожка (.mp3), Видео с субтитрами (.mp4).

### 4. История / History
**Purpose**: Browse past translations.
**Layout**: Centered list, max-width 700px, each entry a glass row (18px radius): colored dot (accent = realtime, 60% white = file) + title + meta line (from→to, duration, date) + "Скачать ↓" link.

### 5. Настройки / Settings
**Purpose**: Defaults and account.
**Layout**: Centered stack of glass group panels (20px radius, 22×24px padding), each with an uppercase 11px section label:
- **Языки по умолчанию**: from/to language pill-selects with a → separator.
- **Голосовой перевод**: on/off glass toggle switch (38×21px pill, knob slides 2px→19px) + when on, a voice picker (Нейтральный / Мужской / Женский) as glass chips.
- **Формат субтитров**: SRT / VTT / TXT chip group.
- **Уведомления**: on/off toggle, "Уведомлять о завершении обработки файла".
- **Аккаунт**: avatar circle (accent fill) + name "Мария Иванова" + email + "Выйти" link.

## Interactions & Behavior
- Top nav is a single persistent pill bar with 5 items (Главная / Реальное время / Загрузка / История / Настройки); active item is a solid white pill with dark text, inactive items are 75%-white text on transparent.
- Language `<select>` pair is shared/synced between the Realtime and Settings screens (same from/to state) with a swap control that transposes the pair.
- Recording toggle starts a caption-reveal timer (demo: 1.8s interval, 4 scripted lines, then stops); stopping clears the timer and surfaces the post-recording export actions.
- Upload demo button starts a progress timer (demo: +5% every 140ms) that flips to the "done" state at 100% and can be reset via "Другой файл".
- Mode switch (Субтитры/Текст+озвучка/Разговор) changes both the transcript layout (single centered column vs. left/right conversation bubbles) and whether a speaker label is shown.
- All toggles (voiceover, notifications) are simple on/off state with the accent color indicating "on".
- No hover states were explicitly designed beyond `cursor: pointer` on clickable elements — add subtle hover/focus states (e.g., +4% white background, focus ring in accent) when implementing, since the prototype doesn't specify them.

## State Management
Minimal client state, no backend wired up (this is a prototype):
- `activeScreen`: 'home' | 'realtime' | 'upload' | 'history' | 'settings'
- `fromLang`, `toLang`: language codes (shared across screens)
- `realtimeMode`: 'subtitles' | 'voice' | 'conversation'
- `recording`: boolean, `captionIndex`: number (drives which demo caption lines are shown)
- `uploadStage`: 'idle' | 'processing' | 'done', `uploadProgress`: number 0–100
- `voiceoverOn`, `voice` ('neutral'|'male'|'female'), `subFormat` ('srt'|'vtt'|'txt'), `notifyOn`: settings state
- Real implementation needs: actual mic capture + streaming ASR/MT/TTS pipeline for Realtime; real file upload + processing job polling for Upload; persisted history from a backend; persisted user settings.

## Design Tokens
- **Base background**: `#04060c` (page), `#0d0f1a` (dropdown option background, dark chip text color used on filled accent elements)
- **Accent (tweakable)**: default `#7fa4ff`; alternates `#b98cff`, `#5ee6c9`, `#ff9d7a`
- **Text**: white at 100% (primary), 75% (secondary), 55–65% (tertiary/meta), 40% (placeholder/empty state)
- **Radius scale**: 999px (pill: nav, buttons, chips, toggles), 24–28px (large panels), 18–22px (cards, rows), 4–8px (small glyphs)
- **Blur scale**: 20px (small chips/pills), 24–26px (cards), 28px (large panels/dropzone)
- **Type scale**: 52px/700 (H1), 36–42px/700 (screen titles), 29px/700 (card titles), 18–26px (emphasis text), 14–15px (body), 12–13px (secondary/buttons), 10.5–11px uppercase (eyebrows/labels)
- **Spacing**: 4/8/10/12/14/16/18/20/22/24/28/32/36/40/52/56px used across gaps/padding — no strict 8pt grid, but values cluster around multiples of 2px

## Assets
- `assets/bg-translate.png` — full-bleed background illustration (AI-generated placeholder depicting network lines, a world map, and floating language-tag bubbles). Replace with final brand artwork or an on-brand equivalent; keep similar composition (clear space in the upper-middle area, since UI content sits on top) if reused.
- No icon set was designed — nav, toggles, and buttons use plain shapes (circles, pills) and text; add a proper icon set (mic, upload, download, chevron, etc.) during implementation.

## Files
- `Auris - Аудиопереводчик.dc.html` — full interactive prototype (all 5 screens, in-file state/demo logic). Open directly in a browser to review behavior.
- `assets/bg-translate.png` — background image referenced above.
