import os, sys, pathlib, re, time
base = pathlib.Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
for sub in sorted(base.glob("*/bin")):
    os.add_dll_directory(str(sub.resolve()))
import ctranslate2, transformers
MP = r"E:\LanguageTranscriptor\models\hub\models--entai2965--nllb-200-distilled-600M-ctranslate2\snapshots\86876131d0a16b17ced0a5c558fdc3e4613ae545"
tr = ctranslate2.Translator(MP, device="cuda", compute_type="int8_float16")
tok = transformers.AutoTokenizer.from_pretrained(MP, src_lang="eng_Latn")

src = ("Good morning everyone, and thank you for joining this quarterly review. "
       "Our team reduced average response latency by thirty-one percent. "
       "We also cut infrastructure spending by twelve thousand dollars per month.")

def translate(sents, tgt):
    batch = [tok.convert_ids_to_tokens(tok.encode(s)) for s in sents]
    r = tr.translate_batch(batch, target_prefix=[[tgt]]*len(batch), beam_size=4)
    return [tok.decode(tok.convert_tokens_to_ids(h.hypotheses[0][1:])) for h in r]

for tgt in ["zho_Hans", "jpn_Jpan", "deu_Latn"]:
    whole = translate([src], tgt)[0]
    sents = re.split(r'(?<=[.!?])\s+', src.strip())
    t = time.perf_counter()
    parts = translate(sents, tgt)
    el = time.perf_counter() - t
    print(f"\n=== {tgt} ===")
    print(f"  WHOLE ({len(whole)} chars): {whole}")
    print(f"  SPLIT ({sum(len(p) for p in parts)} chars, {len(sents)} sents, {el*1000:.0f} ms batched):")
    for p in parts: print(f"     - {p}")
