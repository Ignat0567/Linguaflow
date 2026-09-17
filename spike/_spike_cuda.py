import os, sys, pathlib
base = pathlib.Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
found = []
for sub in sorted(base.glob("*/bin")):
    os.add_dll_directory(str(sub.resolve()))
    found.append(sub.parent.name)
print("dll dirs:", found)
import ctranslate2
print("ctranslate2", ctranslate2.__version__)
print("cuda device count:", ctranslate2.get_cuda_device_count())
print("supported compute types:", ctranslate2.get_supported_compute_types("cuda") if ctranslate2.get_cuda_device_count() else "n/a")
