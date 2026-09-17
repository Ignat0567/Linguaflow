import time, wave, io
from piper import PiperVoice
cases = [
    ("models/piper/de_DE-thorsten-medium.onnx",
     "Guten Morgen und vielen Dank, dass Sie sich an dieser vierteljährlichen Überprüfung beteiligt haben."),
    ("models/piper/ja_JA-hi_fi_captain-medium.onnx",
     "皆さん、おはようございます。私たちのチームは平均応答遅延を31パーセント削減しました。"),
    ("models/piper/zh_CN-huayan-medium.onnx",
     "大家早上好，感谢各位参加本次季度回顾会议。"),
]
for path, text in cases:
    v = PiperVoice.load(path)
    t = time.perf_counter()
    chunks = list(v.synthesize(text))
    el = time.perf_counter() - t
    sr = chunks[0].sample_rate
    n = sum(len(c.audio_int16_bytes) for c in chunks) // 2
    audio_s = n / sr
    out = path.split("/")[-1].replace(".onnx", ".wav")
    with wave.open(f"_spike_audio/tts_{out}", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        for c in chunks: w.writeframes(c.audio_int16_bytes)
    print(f"{out:40s} audio {audio_s:5.2f}s | synth {el:5.2f}s | RTF {el/audio_s:.3f} | sr {sr}")
