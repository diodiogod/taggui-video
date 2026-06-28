"""Sequential stage-major execution for named automation pipelines."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, QObject, Qt, QTimer, Signal

from auto_captioning.captioning_thread import CaptioningThread
from auto_marking.marking_thread import MarkingThread
from utils.ideogram_caption import (
    IdeogramCaptionError,
    merge_image_markings_into_ideogram,
)
from utils.pipeline import PipelineDefinition, PipelineStep
from utils.settings import DEFAULT_SETTINGS, get_tag_separator, settings


class PipelineRunner(QObject):
    """Run pipeline steps in order while keeping long model stages asynchronous."""

    running_changed = Signal(bool)
    step_started = Signal(int, int, str)
    progress_changed = Signal(int, int, str)
    log_message = Signal(str)
    finished = Signal(bool, str)

    STEP_TITLES = {
        "auto_mark": "Auto Marking",
        "build_ideogram_regions": "Build Ideogram Regions",
        "auto_caption": "Auto Caption",
        "save": "Save Metadata",
    }

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.pipeline: PipelineDefinition | None = None
        self.image_indices: list[QModelIndex] = []
        self.steps: list[PipelineStep] = []
        self.step_index = -1
        self.active_thread = None
        self.is_running = False
        self.cancel_requested = False

    def run_pipeline(
        self,
        pipeline: PipelineDefinition,
        image_indices: list[QModelIndex],
    ) -> bool:
        if self.is_running:
            return False
        pipeline.validate()
        valid_indices = [index for index in image_indices if index.isValid()]
        if not valid_indices:
            self.finished.emit(False, "No images are available in the selected scope.")
            return False
        self.pipeline = pipeline
        self.image_indices = valid_indices
        self.steps = [step for step in pipeline.steps if step.enabled]
        if not self.steps:
            self.finished.emit(False, "The pipeline has no enabled steps.")
            return False
        self.step_index = -1
        self.cancel_requested = False
        self.is_running = True
        self.running_changed.emit(True)
        self.log_message.emit(
            f"Running {pipeline.name} on {len(valid_indices)} item(s)."
        )
        QTimer.singleShot(0, self._advance)
        return True

    def cancel(self):
        if not self.is_running:
            return
        self.cancel_requested = True
        thread = self.active_thread
        if thread is not None:
            request_cancel = getattr(thread, "request_cancel", None)
            if callable(request_cancel):
                request_cancel()
            else:
                thread.is_canceled = True
        self.log_message.emit("Cancel requested. Finishing the active operation...")

    def _advance(self):
        if self.cancel_requested:
            self._finish(False, "Pipeline canceled.")
            return
        self.step_index += 1
        if self.step_index >= len(self.steps):
            self._finish(True, "Pipeline completed.")
            return
        step = self.steps[self.step_index]
        title = self.STEP_TITLES[step.type]
        self.step_started.emit(self.step_index + 1, len(self.steps), title)
        self.log_message.emit(
            f"Step {self.step_index + 1}/{len(self.steps)}: {title}"
        )
        try:
            if step.type == "auto_mark":
                self._start_auto_mark(step)
            elif step.type == "build_ideogram_regions":
                self._run_build_ideogram()
            elif step.type == "auto_caption":
                self._start_auto_caption(step)
            elif step.type == "save":
                self._run_save()
        except Exception as exc:
            self._finish(False, f"{title} failed: {exc}")

    def _start_auto_mark(self, step: PipelineStep):
        model_value = str(step.settings.get("model") or "").strip()
        if not model_value:
            model_value = str(
                self.main_window.auto_markings.marking_settings_form.model_combo_box.currentText()
                or ""
            ).strip()
        model_path = Path(model_value).expanduser()
        if not model_path.is_absolute():
            root = settings.value(
                "marking_models_directory_path",
                DEFAULT_SETTINGS["marking_models_directory_path"],
                type=str,
            )
            model_path = Path(root) / model_path if root else model_path
        if not model_path.exists():
            raise FileNotFoundError(f"Auto-marking model not found: {model_path}")

        class_names = step.settings.get("class_names", [])
        if isinstance(class_names, str):
            class_names = [part.strip() for part in class_names.split(",") if part.strip()]
        marking_settings = {
            "model_path": model_path,
            "conf": float(step.settings.get("confidence", 0.25)),
            "iou": float(step.settings.get("iou", 0.7)),
            "max_det": int(step.settings.get("max_detections", 300)),
            "merge_overlaps": bool(step.settings.get("merge_overlaps", False)),
            "merge_overlap_threshold": float(
                step.settings.get("merge_overlap_threshold", 0.6)
            ),
            "marking_type": str(step.settings.get("marking_type", "hint")),
            "class_names": list(class_names),
            "classes": {},
        }
        images = [
            self.main_window.image_list_model.data(index, Qt.ItemDataRole.UserRole)
            for index in self.image_indices
        ]
        self.main_window.image_list_model.add_images_to_undo_stack(
            [image for image in images if image is not None],
            action_name="Pipeline auto marking",
            should_ask_for_confirmation=False,
        )
        thread = MarkingThread(
            self,
            self.main_window.image_list_model,
            self.image_indices,
            marking_settings,
        )
        thread.marking_generated.connect(
            self._add_exact_new_markings
        )
        self._start_thread(thread)

    def _add_exact_new_markings(self, image_index: QModelIndex, markings: list[dict]):
        image = self.main_window.image_list_model.data(
            image_index,
            Qt.ItemDataRole.UserRole,
        )
        if image is None:
            return
        existing = {
            (
                str(marking.label or ""),
                str(getattr(marking.type, "value", marking.type)),
                marking.rect.normalized().getRect(),
            )
            for marking in image.markings
        }
        unique = []
        for marking in markings:
            box = marking.get("box", [])
            if len(box) != 4:
                continue
            marking_type = {
                "hint": "hint",
                "include": "include in mask",
                "exclude": "exclude from mask",
            }.get(str(marking.get("type")), str(marking.get("type")))
            from math import ceil, floor
            rect_key = (
                floor(float(box[0])),
                floor(float(box[1])),
                ceil(float(box[2])) - floor(float(box[0])) + 1,
                ceil(float(box[3])) - floor(float(box[1])) + 1,
            )
            key = (str(marking.get("label") or ""), marking_type, rect_key)
            if key in existing:
                continue
            existing.add(key)
            unique.append(marking)
        if unique:
            self.main_window.image_list_model.add_image_markings(
                image_index,
                unique,
            )

    def _start_auto_caption(self, step: PipelineStep):
        form = self.main_window.auto_captioner.caption_settings_form
        caption_settings = form.get_caption_settings()
        model_id = str(step.settings.get("model") or "").strip()
        if model_id:
            caption_settings["model_id"] = model_id
        caption_settings["output_format"] = str(
            step.settings.get("output_format") or "Ideogram 4 JSON"
        )
        if "remote_structured_output" in step.settings:
            caption_settings["remote_ideogram_structured_output"] = bool(
                step.settings["remote_structured_output"]
            )
        models_directory = settings.value(
            "models_directory_path",
            DEFAULT_SETTINGS["models_directory_path"],
            type=str,
        )
        thread = CaptioningThread(
            self,
            self.main_window.image_list_model,
            self.image_indices,
            caption_settings,
            get_tag_separator(),
            Path(models_directory) if models_directory else None,
            self.main_window.image_viewer,
        )
        thread.caption_generated.connect(
            self.main_window.auto_captioner.caption_generated.emit
        )
        thread.structured_caption_generated.connect(
            self.main_window.auto_captioner.structured_caption_generated.emit
        )
        self._start_thread(thread)

    def _start_thread(self, thread):
        self.active_thread = thread
        thread.text_outputted.connect(self.log_message.emit)
        thread.progress_bar_update_requested.connect(
            lambda value: self.progress_changed.emit(
                int(value), len(self.image_indices), self.STEP_TITLES[self.steps[self.step_index].type]
            )
        )
        thread.finished.connect(self._thread_finished)
        thread.start()

    def _thread_finished(self):
        thread = self.active_thread
        self.active_thread = None
        if thread is None:
            return
        if self.cancel_requested or bool(getattr(thread, "is_canceled", False)):
            self._finish(False, "Pipeline canceled.")
            return
        if bool(getattr(thread, "is_error", False)):
            message = str(getattr(thread, "error_message", "") or "Model step failed.")
            self._finish(False, message)
            return
        QTimer.singleShot(0, self._advance)

    def _run_build_ideogram(self):
        added_total = 0
        failures = []
        for position, index in enumerate(self.image_indices, start=1):
            if self.cancel_requested:
                self._finish(False, "Pipeline canceled.")
                return
            image = self.main_window.image_list_model.data(
                index, Qt.ItemDataRole.UserRole
            )
            if image is None:
                continue
            try:
                _caption, added = merge_image_markings_into_ideogram(image)
                added_total += added
                self.main_window.image_list_model.refresh_ideogram_caption_index_for_image(
                    image
                )
            except (IdeogramCaptionError, OSError) as exc:
                failures.append(f"{image.path.name}: {exc}")
            self.progress_changed.emit(
                position, len(self.image_indices), "Build Ideogram Regions"
            )
        self.log_message.emit(f"Added {added_total} Ideogram region(s).")
        if failures:
            self.log_message.emit("Skipped: " + "; ".join(failures[:5]))
        self._refresh_ideogram_ui()
        QTimer.singleShot(0, self._advance)

    def _run_save(self):
        for position, index in enumerate(self.image_indices, start=1):
            image = self.main_window.image_list_model.data(
                index, Qt.ItemDataRole.UserRole
            )
            if image is None:
                continue
            self.main_window.image_list_model.write_image_tags_to_disk(image)
            self.main_window.image_list_model.write_meta_to_disk(image)
            self.main_window.image_list_model.refresh_ideogram_caption_index_for_image(
                image
            )
            self.progress_changed.emit(position, len(self.image_indices), "Save Metadata")
        QTimer.singleShot(0, self._advance)

    def _refresh_ideogram_ui(self):
        self.main_window.image_viewer.refresh_ideogram_caption_overlays()
        self.main_window.image_tags_editor.reload_ideogram_caption_for_current_image()
        current_image = self.main_window.image_viewer.proxy_image_index.data(
            Qt.ItemDataRole.UserRole
        ) if self.main_window.image_viewer.proxy_image_index.isValid() else None
        self.main_window.ideogram_caption_editor.load_media(current_image)

    def _finish(self, success: bool, message: str):
        if not self.is_running:
            return
        self.is_running = False
        self.active_thread = None
        self.running_changed.emit(False)
        self.log_message.emit(message)
        self.finished.emit(success, message)
