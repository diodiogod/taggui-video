from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog
from utils.settings import DEFAULT_SETTINGS, settings


_CACHE_DIR = Path.home() / ".taggui_cache" / "marking_models"
_TRUSTED_MODELS_SETTINGS_KEY = "trusted_marking_models_json"
_KNOWN_MODEL_TASKS = ("semantic", "segment", "classify", "pose", "obb", "detect")


def list_marking_model_paths(models_directory_path: Path) -> list[Path]:
    base = Path(models_directory_path)
    onnx_paths = sorted(base.glob("**/*.onnx"))
    onnx_keys = {
        str(path.relative_to(base).with_suffix("")).replace("\\", "/")
        for path in onnx_paths
    }
    pt_paths = [
        path for path in sorted(base.glob("**/*.pt"))
        if str(path.relative_to(base).with_suffix("")).replace("\\", "/") not in onnx_keys
    ]
    return onnx_paths + pt_paths


def resolve_marking_model_value(model_value: str, models_root: str | Path) -> Path:
    model_path = Path(str(model_value or "").strip()).expanduser()
    if not model_path.is_absolute():
        root = Path(str(models_root or "")).expanduser()
        model_path = root / model_path if str(root) else model_path
    return model_path


def preferred_runtime_path(model_path: Path) -> Path:
    model_path = Path(model_path).expanduser()
    if model_path.suffix.lower() == ".onnx":
        return model_path
    sibling_onnx = model_path.with_suffix(".onnx")
    if sibling_onnx.is_file():
        return sibling_onnx
    imported_sibling = imported_onnx_output_path(model_path)
    if imported_sibling.is_file():
        return imported_sibling
    cached_onnx = cached_imported_onnx_path(model_path)
    if cached_onnx.is_file():
        return cached_onnx
    return model_path


def configure_ultralytics_marking_runtime(model_path: Path):
    model_path = Path(model_path).expanduser()
    if model_path.suffix.lower() != ".onnx":
        return
    try:
        from ultralytics.nn.backends import onnx as onnx_backend
    except Exception:
        return
    if getattr(onnx_backend, "_taggui_safe_requirements_patch", False):
        return

    original_check_requirements = onnx_backend.check_requirements

    def safe_check_requirements(requirements=(), *args, **kwargs):
        candidates = requirements if isinstance(requirements, (list, tuple)) else [requirements]
        flattened = []
        for candidate in candidates:
            if isinstance(candidate, (list, tuple)):
                flattened.extend(str(item).lower() for item in candidate)
            else:
                flattened.append(str(candidate).lower())
        if any("onnxruntime" in item or item.startswith("onnx") for item in flattened):
            try:
                import onnx  # noqa: F401
                import onnxruntime  # noqa: F401
                return True
            except Exception:
                patched_kwargs = dict(kwargs)
                patched_kwargs["install"] = False
                return original_check_requirements(requirements, *args, **patched_kwargs)
        return original_check_requirements(requirements, *args, **kwargs)

    onnx_backend.check_requirements = safe_check_requirements
    onnx_backend._taggui_safe_requirements_patch = True


def _infer_task_from_name(model_path: Path) -> str | None:
    lower_stem = model_path.stem.lower()
    lower_parts = [part.lower() for part in model_path.parts]
    if "-sem" in lower_stem or "semantic" in lower_parts:
        return "semantic"
    if "-seg" in lower_stem or "segment" in lower_parts or "_seg" in lower_stem:
        return "segment"
    if "-cls" in lower_stem or "classify" in lower_parts:
        return "classify"
    if "-pose" in lower_stem or "pose" in lower_parts:
        return "pose"
    if "-obb" in lower_stem or "obb" in lower_parts:
        return "obb"
    if "detect" in lower_parts:
        return "detect"
    return None


def _infer_task_from_onnx_metadata(model_path: Path) -> str | None:
    try:
        import onnxruntime
    except Exception:
        return None
    try:
        session = onnxruntime.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
    except Exception:
        return None
    metadata = getattr(session.get_modelmeta(), "custom_metadata_map", {}) or {}
    task = str(metadata.get("task") or "").strip().lower()
    return task if task in _KNOWN_MODEL_TASKS else None


def _infer_task_from_file_bytes(model_path: Path) -> str | None:
    try:
        if zipfile.is_zipfile(model_path):
            with zipfile.ZipFile(model_path) as archive:
                for name in archive.namelist():
                    if not name.endswith((".pkl", ".yaml", ".yml", ".json")):
                        continue
                    with archive.open(name) as handle:
                        data = handle.read().lower()
                    for task in _KNOWN_MODEL_TASKS:
                        if task.encode("utf-8") in data:
                            return task
            return None
        data = model_path.read_bytes().lower()
    except Exception:
        return None
    for task in _KNOWN_MODEL_TASKS:
        if task.encode("utf-8") in data:
            return task
    return None


def infer_marking_model_task(model_path: Path | str | None) -> str | None:
    if not model_path:
        return None
    resolved = Path(model_path).expanduser()
    task = _infer_task_from_name(resolved)
    if task and task != "detect":
        return task
    if resolved.suffix.lower() == ".onnx":
        task = _infer_task_from_onnx_metadata(resolved)
        if task:
            return task
    task = _infer_task_from_file_bytes(resolved)
    if task:
        return task
    return _infer_task_from_name(resolved)


def cached_imported_onnx_path(pt_path: Path) -> Path:
    resolved = Path(pt_path).expanduser().resolve()
    stat = resolved.stat()
    hash_input = f"{resolved}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8", "replace")
    cache_key = hashlib.sha256(hash_input).hexdigest()
    return _CACHE_DIR / f"{cache_key}.onnx"


def imported_onnx_output_path(pt_path: Path) -> Path:
    return Path(pt_path).with_suffix(".onnx")


def _preferred_import_output_path(pt_path: Path) -> Path:
    sibling_output = imported_onnx_output_path(pt_path)
    try:
        sibling_output.parent.mkdir(parents=True, exist_ok=True)
        with sibling_output.parent.joinpath(".taggui_write_test").open("a", encoding="utf-8"):
            pass
        sibling_output.parent.joinpath(".taggui_write_test").unlink(missing_ok=True)
        return sibling_output
    except Exception:
        return cached_imported_onnx_path(pt_path)


def compute_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _load_trusted_models() -> dict[str, dict[str, str]]:
    raw = settings.value(
        _TRUSTED_MODELS_SETTINGS_KEY,
        DEFAULT_SETTINGS[_TRUSTED_MODELS_SETTINGS_KEY],
        type=str,
    )
    try:
        parsed = json.loads(raw or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _save_trusted_models(payload: dict[str, dict[str, str]]):
    settings.setValue(_TRUSTED_MODELS_SETTINGS_KEY, json.dumps(payload))


def trust_marking_model(path: Path, *, mode: str):
    sha256 = compute_file_sha256(path)
    payload = _load_trusted_models()
    payload[sha256] = {
        "path": str(Path(path).expanduser()),
        "mode": str(mode),
    }
    _save_trusted_models(payload)


def trusted_marking_model_mode(path: Path) -> str | None:
    sha256 = compute_file_sha256(path)
    payload = _load_trusted_models()
    entry = payload.get(sha256)
    if not isinstance(entry, dict):
        return None
    mode = str(entry.get("mode") or "").strip().lower()
    return mode if mode in {"direct", "import"} else None


def passive_model_warning_text(path: Path | None) -> str:
    if path is None:
        return ""
    model_path = Path(path).expanduser()
    if model_path.suffix.lower() != ".pt":
        return ""
    trusted_mode = trusted_marking_model_mode(model_path)
    preferred = preferred_runtime_path(model_path)
    if preferred.suffix.lower() == ".onnx" and preferred.is_file():
        if trusted_mode == "import":
            return (
                "PT source selected. TagGUI will prefer the imported ONNX copy for safer runs."
            )
        return (
            "PT source selected. A local ONNX runtime copy is available and will be preferred."
        )
    if trusted_mode == "direct":
        return (
            "Warning: this PT model is trusted for direct loading. PyTorch .pt checkpoints can execute code."
        )
    if trusted_mode == "import":
        return (
            "PT source selected. TagGUI is set to import it to ONNX before use, which is safer but not fully safe."
        )
    return (
        "Warning: PyTorch .pt checkpoints can execute code. TagGUI will offer ONNX import or an explicit unsafe fallback when you run this model."
    )


def open_virustotal_for_file(path: Path, *, parent=None):
    file_path = Path(path).expanduser()
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        sha256 = compute_file_sha256(file_path)
    finally:
        QApplication.restoreOverrideCursor()
    QDesktopServices.openUrl(QUrl(f"https://www.virustotal.com/gui/file/{sha256}"))
    if parent is not None:
        QMessageBox.information(
            parent,
            "VirusTotal",
            "Opened the model hash on VirusTotal. If there is no existing report, "
            "you may need to upload the file manually. Do not assume a clean report "
            "means the model is safe.",
        )


def _launch_import_command(pt_path: Path, output_path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--import-marking-model", str(pt_path), str(output_path)]
    launcher = Path(__file__).resolve().parents[2] / "run_taggui.py"
    return [sys.executable, str(launcher), "--import-marking-model", str(pt_path), str(output_path)]


def import_pt_model_to_onnx(pt_path: Path, *, parent=None) -> Path:
    output_path = _preferred_import_output_path(pt_path)
    if output_path.is_file():
        return output_path

    if output_path.parent == _CACHE_DIR:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    command = _launch_import_command(pt_path, output_path)
    progress = QProgressDialog(
        "Importing PT model to ONNX in a helper process...",
        "Cancel",
        0,
        0,
        parent,
    )
    progress.setWindowTitle("Import Marking Model")
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.show()

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        while process.poll() is None:
            QApplication.processEvents()
            if progress.wasCanceled():
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError("Canceled PT import.")
            time.sleep(0.1)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        progress.close()
        progress.deleteLater()

    if process.returncode != 0:
        message = (stderr or stdout or "").strip() or "PT import failed."
        raise RuntimeError(message)
    if not output_path.is_file():
        message = (stdout or "").strip()
        if message:
            exported_path = Path(message).expanduser()
            if exported_path.is_file():
                return exported_path
        raise RuntimeError("PT import finished without producing an ONNX file.")
    return output_path


def prompt_resolve_runtime_path(model_path: Path, *, parent=None, purpose: str = "run") -> Path:
    model_path = Path(model_path).expanduser()
    preferred = preferred_runtime_path(model_path)
    if preferred.suffix.lower() == ".onnx" and preferred.is_file():
        return preferred
    if model_path.suffix.lower() != ".pt":
        return model_path

    trusted_mode = trusted_marking_model_mode(model_path)
    if trusted_mode == "import":
        return import_pt_model_to_onnx(model_path, parent=parent)
    if trusted_mode == "direct":
        return model_path

    purpose_text = "run this model" if purpose == "run" else "inspect this model"
    while True:
        dialog = QMessageBox(parent)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("PT Model Security")
        dialog.setText(
            "This model is a PyTorch .pt checkpoint. Loading it directly can run "
            "malicious code. TagGUI can import it to ONNX in a separate helper "
            "process, which is safer but still not fully safe."
        )
        dialog.setInformativeText(
            f"Choose how to {purpose_text}:\n\n"
            "Import to ONNX: safer default and stored next to the PT file when possible.\n"
            "Check VirusTotal: opens a hash lookup in your browser.\n"
            "Run PT Directly: unsafe fallback for trusted models only."
        )
        import_button = dialog.addButton("Import to ONNX", QMessageBox.ButtonRole.AcceptRole)
        trust_import_button = dialog.addButton("Always Trust and Import", QMessageBox.ButtonRole.YesRole)
        vt_button = dialog.addButton("Check VirusTotal", QMessageBox.ButtonRole.ActionRole)
        unsafe_button = dialog.addButton("Run PT Directly", QMessageBox.ButtonRole.DestructiveRole)
        trust_direct_button = dialog.addButton("Always Trust and Run PT", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(import_button)
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked == import_button:
            return import_pt_model_to_onnx(model_path, parent=parent)
        if clicked == trust_import_button:
            trust_marking_model(model_path, mode="import")
            return import_pt_model_to_onnx(model_path, parent=parent)
        if clicked == vt_button:
            open_virustotal_for_file(model_path, parent=parent)
            continue
        if clicked == unsafe_button:
            return model_path
        if clicked == trust_direct_button:
            trust_marking_model(model_path, mode="direct")
            return model_path
        if clicked == cancel_button or clicked is None:
            raise RuntimeError("Model load canceled.")
