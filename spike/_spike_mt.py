import os, sys, pathlib, time
base = pathlib.Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
for sub in sorted(base.glob("*/bin")):
    os.add_dll_directory(str(sub.resolve()))
import ctranslate2, transformers

MP = r"E:\LanguageTranscriptor\models\hub\models--entai2965--nllb-200-distilled-600M-ctranslate2\snapshots\86876131d0a16b17ced0a5c558fdc3e4613ae545"
LANG = {"en":"eng_Latn","de":"deu_Latn","ru":"rus_Cyrl","zh":"zho_Hans",
        "ja":"jpn_Jpan","es":"spa_Latn","it":"ita_Latn","fr":"fra_Latn"}

t0=time.perf_counter()
tr = ctranslate2.Translator(MP, device="cuda", compute_type="int8_float16")
tok = transformers.AutoTokenizer.from_pretrained(MP, src_lang="eng_Latn")
print(f"MT load: {time.perf_counter()-t0:.1f}s")

src = "Good morning everyone, and thank you for joining this quarterly review. Our team reduced average response latency by thirty-one percent."
toks = tok.convert_ids_to_tokens(tok.encode(src))

for code, nllb in LANG.items():
    if code == "en": continue
    t=time.perf_counter()
    res = tr.translate_batch([toks], target_prefix=[[nllb]], beam_size=4)
    el=time.perf_counter()-t
    out = tok.decode(tok.convert_tokens_to_ids(res[0].hypotheses[0][1:]))
    print(f"en->{code} [{el*1000:6.0f} ms]  {out}")

# reverse direction check: ru -> de
tok2 = transformers.AutoTokenizer.from_pretrained(MP, src_lang="rus_Cyrl")
ru = "Доброе утро, благодарю вас за участие в этой встрече."
t=time.perf_counter()
res = tr.translate_batch([tok2.convert_ids_to_tokens(tok2.encode(ru))], target_prefix=[["deu_Latn"]], beam_size=4)
print(f"ru->de [{(time.perf_counter()-t)*1000:6.0f} ms]  {tok2.decode(tok2.convert_tokens_to_ids(res[0].hypotheses[0][1:]))}")
