import os, sys, pathlib, time, wave
base = pathlib.Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
for sub in sorted(base.glob("*/bin")):
    os.add_dll_directory(str(sub.resolve()))
from faster_whisper import WhisperModel

MODEL = r"E:\LanguageTranscriptor\models\hub\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo\snapshots\0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
AUD = pathlib.Path(r"E:\LanguageTranscriptor\_spike_audio")

def dur(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()

t0 = time.perf_counter()
m = WhisperModel(MODEL, device="cuda", compute_type="int8_float16")
print(f"model load: {time.perf_counter()-t0:.1f}s")

for name in ["en.wav", "de.wav", "ru.wav"]:
    p = AUD / name
    d = dur(p)
    for run in (1, 2):   # run 1 = cold, run 2 = warm
        t = time.perf_counter()
        segs, info = m.transcribe(str(p), beam_size=5, vad_filter=True)
        text = " ".join(s.text.strip() for s in segs)
        el = time.perf_counter() - t
        if run == 2:
            print(f"\n{name}: audio {d:.1f}s | asr {el:.2f}s | RTF {el/d:.3f} | "
                  f"detected={info.language} p={info.language_probability:.2f}")
            print(f"  -> {text[:160]}")
