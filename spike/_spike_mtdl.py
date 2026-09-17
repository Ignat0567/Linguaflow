from huggingface_hub import snapshot_download
for repo in ["entai2965/nllb-200-distilled-600M-ctranslate2",
             "JustFrederik/nllb-200-distilled-600M-ct2-int8"]:
    try:
        p = snapshot_download(repo)
        print("OK:", repo, "->", p); break
    except Exception as e:
        print("FAIL:", repo, type(e).__name__, str(e)[:120])
