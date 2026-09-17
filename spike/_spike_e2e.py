import os, sys, pathlib, re, time, wave, numpy as np
base = pathlib.Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
for sub in sorted(base.glob("*/bin")):
    os.add_dll_directory(str(sub.resolve()))
from faster_whisper import WhisperModel
import ctranslate2, transformers
from piper import PiperVoice

ASR = r"E:\LanguageTranscriptor\models\hub\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo\snapshots\0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
MT  = r"E:\LanguageTranscriptor\models\hub\models--entai2965--nllb-200-distilled-600M-ctranslate2\snapshots\86876131d0a16b17ced0a5c558fdc3e4613ae545"

print("loading models...")
asr = WhisperModel(ASR, device="cuda", compute_type="int8_float16")
mt  = ctranslate2.Translator(MT, device="cuda", compute_type="int8_float16")
tok = transformers.AutoTokenizer.from_pretrained(MT, src_lang="eng_Latn")
tts = PiperVoice.load("models/piper/de_DE-thorsten-medium.onnx")

with wave.open("_spike_audio/en.wav") as w:
    sr = w.getframerate()
    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)/32768.0
if sr != 16000:
    idx = (np.arange(int(len(pcm)*16000/sr)) * sr/16000).astype(np.int64)
    pcm = pcm[np.clip(idx, 0, len(pcm)-1)]

CHUNK = 5.0
print(f"\nsimulating live pipeline, chunk={CHUNK}s, en -> de (voice + subtitles)\n")
tot = []
for i in range(4):
    seg = pcm[int(i*CHUNK*16000):int((i+1)*CHUNK*16000)]
    if len(seg) < 16000: break
    t0=time.perf_counter()
    segs, _ = asr.transcribe(seg, language="en", beam_size=5, vad_filter=True)
    text = " ".join(s.text.strip() for s in segs)
    t1=time.perf_counter()
    if not text: continue
    sents = [s for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s]
    batch = [tok.convert_ids_to_tokens(tok.encode(s)) for s in sents]
    r = mt.translate_batch(batch, target_prefix=[["deu_Latn"]]*len(batch), beam_size=4)
    de = " ".join(tok.decode(tok.convert_tokens_to_ids(h.hypotheses[0][1:])) for h in r)
    t2=time.perf_counter()
    first = next(iter(tts.synthesize(de)))
    t3=time.perf_counter()
    tot.append((t1-t0, t2-t1, t3-t2))
    print(f"chunk {i}: asr {(t1-t0)*1000:5.0f} ms | mt {(t2-t1)*1000:5.0f} ms | tts-first {(t3-t2)*1000:5.0f} ms "
          f"| processing {(t3-t0)*1000:5.0f} ms")
    print(f"   DE: {de[:110]}")
a = np.array(tot).mean(axis=0)
print(f"\nAVG processing: asr {a[0]*1000:.0f} + mt {a[1]*1000:.0f} + tts {a[2]*1000:.0f} = {a.sum()*1000:.0f} ms")
print(f"END-TO-END perceived latency = chunk {CHUNK:.1f}s + processing {a.sum():.2f}s = {CHUNK + a.sum():.2f}s")
