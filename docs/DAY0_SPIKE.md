# Day 0 spike — measured, not assumed (2026-09-17)

Target languages: en, de, ru, zh, ja, es, it, fr.
Hardware: RTX 3050 8GB, Windows 11, Python 3.12.10.

## Verdict: the plan holds. Every load-bearing assumption verified on this machine.

## Measurements

ASR — faster-whisper large-v3-turbo, int8_float16, CUDA:

| clip | audio | ASR time | RTF | detected lang |
|---|---|---|---|---|
| en | 47.2s | 1.62s | 0.034 | en (p=1.00) |
| de | 17.4s | 0.93s | 0.053 | de (p=1.00) |
| ru | 20.1s | 0.95s | 0.047 | ru (p=1.00) |

Model load: ~2.1s. Transcripts verbatim-correct on all three.

MT — NLLB-200-distilled-600M, CT2 int8_float16, CUDA. All 8 languages produce
fluent output. Per-sentence: 125–477 ms. Model load ~3.1s.

TTS — Piper, CPU:

| voice | audio | synth | RTF |
|---|---|---|---|
| de_DE-thorsten-medium | 4.99s | 0.14s | 0.029 |
| ja_JA-hi_fi_captain-medium | 8.10s | 1.17s | 0.145 |
| zh_CN-huayan-medium | 4.60s | 0.13s | 0.029 |

End-to-end live chain (en -> de, voice + subtitles), 5s chunks:
ASR 516ms + MT 197ms + TTS-first-audio 120ms = **833 ms processing**.

**Compute is not the bottleneck — the chunking strategy is.** Perceived latency is
chunk_size + 0.83s. This is why Day 4 (LocalAgreement + VAD-aligned windows) is the
day that determines whether realtime feels good, and we have ample compute headroom
to spend on overlapping windows.

## Findings that change the implementation

1. **Windows blocks huggingface symlinks** without Developer Mode. Every end user hits
   this. Must set `HF_HUB_DISABLE_SYMLINKS=1` before any model download.
2. **CUDA DLLs live inside the venv** and are invisible to the Windows loader. Must call
   `os.add_dll_directory()` for each `nvidia/*/bin` at startup, before importing
   ctranslate2. Paths must be `.resolve()`d — Store-Python virtualization.
3. **Console encoding is cp1251** here; printing German/Chinese/Japanese crashes.
   Force UTF-8 process-wide.
4. **NLLB silently drops sentences on multi-sentence input.** Reproduced: en->zh lost the
   entire first sentence; en->de was fine. Language-pair dependent, so it would have
   shipped unnoticed. Fix: split into sentences, translate as a batch. Costs nothing
   (batched split was *faster* than whole-input).
5. **NLLB corrupts numbers.** "twelve thousand dollars" -> 12万美元 = $120,000, a 10x
   error on a financial figure. Numbers, names and units must be protected with
   placeholder substitution around the MT call, not trusted to the model.
6. **Japanese TTS needs `pyopenjtalk`, which has no Windows/py312 wheel** and fails to
   build without MSVC+cmake. Use `pyopenjtalk-plus` (prebuilt, provides the same module).
   Without this, Japanese voice output is dead on arrival.
7. **Naive fixed-window chunking cuts words.** Reproduced in the e2e run: chunk 2 emitted
   "Abdeckungsreaktionslatenz" from a sentence sliced mid-phrase. Confirms VAD-aligned
   boundaries are required, not optional.
8. **Audio devices run at mixed sample rates** (44100 Bluetooth vs 48000 others) —
   per-device resampling required. Default output here is Bluetooth, which adds
   150–250ms on top of the TTS path.
9. **Piper output peaks at full scale** (32767) — needs headroom/normalisation before
   mixing with a ducked original track.
