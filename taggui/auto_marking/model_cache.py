from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from utils.marking_model_security import (
    configure_ultralytics_marking_runtime,
    infer_marking_model_task,
)


_METADATA_CACHE_PATH = (
    Path.home() / ".taggui_cache" / "marking_models" / "class_metadata.json"
)
_CACHE_LOCK = threading.RLock()
_RUNTIME_CACHE: dict[tuple[str, int, int], "MarkingRuntime"] = {}


@dataclass
class MarkingRuntime:
    model: object
    device: str
    model_names: dict[int, str]
    inference_lock: threading.RLock


def _model_signature(model_path: Path | str) -> tuple[str, int, int]:
    path = Path(model_path).expanduser().resolve()
    stat = path.stat()
    return str(path), int(stat.st_size), int(stat.st_mtime_ns)


def _preferred_device(model_path: Path) -> str:
    import torch

    if not torch.cuda.is_available():
        return "cpu"
    if model_path.suffix.lower() != ".onnx":
        return "cuda"
    try:
        import onnxruntime
    except Exception:
        return "cpu"
    return (
        "cuda"
        if "CUDAExecutionProvider" in onnxruntime.get_available_providers()
        else "cpu"
    )


def load_marking_runtime(model_path: Path | str) -> MarkingRuntime:
    signature = _model_signature(model_path)
    with _CACHE_LOCK:
        cached = _RUNTIME_CACHE.get(signature)
        if cached is not None:
            return cached

        from ultralytics import YOLO

        path = Path(signature[0])
        configure_ultralytics_marking_runtime(path)
        model = YOLO(path, task=infer_marking_model_task(path))
        model_names = {
            int(class_id): str(class_name)
            for class_id, class_name in model.names.items()
        }
        runtime = MarkingRuntime(
            model=model,
            device=_preferred_device(path),
            model_names=model_names,
            inference_lock=threading.RLock(),
        )
        _RUNTIME_CACHE[signature] = runtime
        _write_class_metadata(signature, model_names)
        return runtime


def get_cached_model_classes(
        model_path: Path | str) -> dict[int, str] | None:
    try:
        signature = _model_signature(model_path)
    except OSError:
        return None
    with _CACHE_LOCK:
        runtime = _RUNTIME_CACHE.get(signature)
        if runtime is not None:
            return dict(runtime.model_names)
        payload = _read_metadata_payload()
        entry = payload.get(signature[0])
        if not isinstance(entry, dict):
            return None
        if (
            int(entry.get("size", -1)) != signature[1]
            or int(entry.get("mtime_ns", -1)) != signature[2]
        ):
            return None
        classes = entry.get("classes")
        if not isinstance(classes, dict):
            return None
        try:
            return {
                int(class_id): str(class_name)
                for class_id, class_name in classes.items()
            }
        except (TypeError, ValueError):
            return None


def _read_metadata_payload() -> dict:
    try:
        with _METADATA_CACHE_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_class_metadata(
        signature: tuple[str, int, int],
        model_names: dict[int, str],
):
    payload = _read_metadata_payload()
    payload[signature[0]] = {
        "size": signature[1],
        "mtime_ns": signature[2],
        "classes": {
            str(class_id): str(class_name)
            for class_id, class_name in model_names.items()
        },
    }
    try:
        _METADATA_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = _METADATA_CACHE_PATH.with_suffix(".tmp")
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
        os.replace(temporary_path, _METADATA_CACHE_PATH)
    except OSError:
        return
