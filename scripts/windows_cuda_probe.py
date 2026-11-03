"""Reuse the Torch CUDA probe while the installation is unchanged for Windows launcher setup."""
import json
import os
import subprocess
import sys
from importlib.metadata import distribution, PackageNotFoundError
from pathlib import Path


def fingerprint():
    torch = distribution("torch")
    paths = [Path(sys.executable), torch.locate_file("torch/__init__.py")]
    cuda_library = torch.locate_file("torch/lib/torch_cuda.dll")
    if cuda_library.exists():
        paths.append(cuda_library)
    try:
        devices = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=uuid,driver_version", "--format=csv,noheader"],
            text=True, stderr=subprocess.DEVNULL, timeout=2,
        ).strip()
    except FileNotFoundError:
        devices = None
    return [devices, torch.version, [p.stat().st_mtime_ns for p in paths],
            {k: v for k, v in os.environ.items()
             if k.startswith(("CUDA_", "NVIDIA_", "PYTORCH_"))}]


def available():
    cache = Path(sys.prefix) / ".taggui-cuda-probe.json"
    try:
        key = fingerprint()
    except (OSError, subprocess.SubprocessError, PackageNotFoundError):
        key = None
    if key is not None and "--refresh" not in sys.argv:
        try:
            saved = json.loads(cache.read_text())
            if isinstance(saved, dict) and saved.get("environment") == key:
                if isinstance(saved.get("available"), bool):
                    return saved["available"]
        except (OSError, ValueError):
            pass

    import torch
    detected = torch.cuda.is_available()
    try:
        if key is not None:
            cache.write_text(json.dumps({"environment": key, "available": detected}))
        else:
            cache.unlink(missing_ok=True)
    except OSError:
        pass
    return detected


if __name__ == "__main__":
    raise SystemExit(0 if available() else 1)
