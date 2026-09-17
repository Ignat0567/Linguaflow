from huggingface_hub import snapshot_download
p = snapshot_download("mobiuslabsgmbh/faster-whisper-large-v3-turbo")
print("MODEL_PATH:", p)
