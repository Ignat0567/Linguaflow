import pyaudiowpatch as pyaudio
p = pyaudio.PyAudio()
try:
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
except OSError:
    print("WASAPI NOT AVAILABLE"); raise SystemExit(1)
default_spk = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
print("default output:", default_spk["name"])
loop = None
for d in p.get_loopback_device_info_generator():
    print("  loopback candidate:", d["name"], "| ch", d["maxInputChannels"], "| sr", int(d["defaultSampleRate"]))
    if default_spk["name"] in d["name"] and loop is None:
        loop = d
print("chosen loopback:", loop["name"] if loop else None)

if loop:
    import numpy as np, time
    sr = int(loop["defaultSampleRate"]); ch = loop["maxInputChannels"]
    frames = []
    st = p.open(format=pyaudio.paInt16, channels=ch, rate=sr, input=True,
                input_device_index=loop["index"], frames_per_buffer=1024)
    t = time.perf_counter()
    while time.perf_counter() - t < 2.0:
        frames.append(st.read(1024, exception_on_overflow=False))
    st.close()
    a = np.frombuffer(b"".join(frames), dtype=np.int16)
    print(f"captured {len(a)/ch/sr:.2f}s, channels={ch}, sr={sr}, peak={np.abs(a).max()}")
p.terminate()
