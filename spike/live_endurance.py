"""Does a long live session stay in step, and stay within memory?

Replays a recording at wall-clock speed and samples lag, buffer size and
resident memory throughout. A session that drifts or leaks does not show it in
the first minute; it shows it in the tenth.
"""
import re, statistics, sys, time, tracemalloc
sys.path.insert(0, ".")
from lt_core.asr.transcriber import Transcriber
from lt_core.audio.capture import FileSource
from lt_core.realtime.session import LiveSession, PACES

clip = sys.argv[1]
pace_name = sys.argv[2] if len(sys.argv) > 2 else "balanced"

t = Transcriber(model_root=r"E:\LanguageTranscriptor\models")
s = LiveSession(t, source_language="en", pace=PACES[pace_name])

tracemalloc.start()
lags, samples = [], []
began = time.perf_counter()
for chunk in FileSource(clip, realtime=True).stream():
    if s.feed(chunk) is None:
        continue
    lag = s.stats.audio_seconds - s.agreement.committed_until
    lags.append(lag)
    if len(lags) % 20 == 0:
        current, _ = tracemalloc.get_traced_memory()
        samples.append((s.stats.audio_seconds, lag, s._buffer_duration,
                        current / 1e6, len(s.agreement.committed)))
s.finish()
peak_mb = tracemalloc.get_traced_memory()[1] / 1e6
tracemalloc.stop()

print(f"pace={pace_name}  audio={s.stats.audio_seconds:.0f}s  wall={time.perf_counter()-began:.0f}s")
print(f"{'мин':>6s} {'lag':>6s} {'буфер':>6s} {'память':>8s} {'слов':>6s}")
for at, lag, buf, mb, words in samples:
    print(f"{at/60:6.1f} {lag:6.1f} {buf:6.1f} {mb:7.1f}M {words:6d}")
half = len(lags) // 2
print(f"\nlag  медиана {statistics.median(lags):.1f}s  "
      f"p95 {sorted(lags)[int(len(lags)*0.95)-1]:.1f}s  худш {max(lags):.1f}s")
print(f"lag  первая половина {statistics.median(lags[:half]):.1f}s  "
      f"вторая {statistics.median(lags[half:]):.1f}s  (дрейф, если растёт)")
print(f"буфер максимум {s.stats.max_buffer_seconds:.1f}s | "
      f"принудительных фиксаций {s.stats.forced_commits} | "
      f"нагрузка {s.stats.realtime_factor:.2f}")
print(f"память пик {peak_mb:.0f} MB | слов зафиксировано "
      f"{len(s.agreement.committed_text.split())}")
