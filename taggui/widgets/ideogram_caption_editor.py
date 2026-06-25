"""Dock editor for Ideogram 4 structured caption sidecars."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QModelIndex, QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from utils.ideogram_caption import (
    IdeogramCaption,
    IdeogramCaptionError,
    IdeogramElement,
    discover_ideogram_caption,
    ideogram_caption_path,
    pixel_rect_to_bbox,
    save_ideogram_caption,
)
from utils.image import Image, ImageMarking


class IdeogramCaptionEditor(QDockWidget):
    """Edit the structured JSON caption associated with the current image."""

    caption_saved = Signal(object)

    def __init__(self, image_viewer, parent=None):
        super().__init__(parent)
        self.image_viewer = image_viewer
        self.current_image: Image | None = None
        self.current_path: Path | None = None
        self.current_caption_path: Path | None = None
        self._loading = False
        self._dirty = False
        self._drafts: dict[Path, str] = {}

        self.setObjectName("ideogram_caption_editor")
        self.setWindowTitle("Ideogram 4 Caption")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.path_label = QLabel("No media selected")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.path_label.setWordWrap(True)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "Select an image, then create or load an Ideogram 4 caption."
        )
        editor_font = QFont("DejaVu Sans Mono")
        editor_font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(editor_font)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)

        self.new_button = QPushButton("New")
        self.from_markings_button = QPushButton("From Markings")
        self.save_button = QPushButton("Save")
        self.reload_button = QPushButton("Reload")
        self.format_button = QPushButton("Format")
        self.copy_button = QPushButton("Copy")

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        for button in (
            self.new_button,
            self.from_markings_button,
            self.save_button,
            self.reload_button,
            self.format_button,
            self.copy_button,
        ):
            button_layout.addWidget(button)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self.path_label)
        layout.addLayout(button_layout)
        layout.addWidget(self.editor, stretch=1)
        layout.addWidget(self.status_label)
        self.setWidget(container)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(900)
        self.autosave_timer.timeout.connect(self._autosave_if_valid)

        self.editor.textChanged.connect(self._on_text_changed)
        self.new_button.clicked.connect(self.create_new_caption)
        self.from_markings_button.clicked.connect(
            self.create_caption_from_markings
        )
        self.save_button.clicked.connect(self.save_caption)
        self.reload_button.clicked.connect(self.reload_caption)
        self.format_button.clicked.connect(self.format_caption)
        self.copy_button.clicked.connect(self.copy_caption)
        self._set_controls_enabled(False)

    def load_image(self, index: QModelIndex):
        """Load the selected image's caption or preserved in-memory draft."""
        if self.current_path is not None and self._dirty:
            self._drafts[self.current_path] = self.editor.toPlainText()

        image = (
            index.data(Qt.ItemDataRole.UserRole)
            if index is not None and index.isValid()
            else None
        )
        self.current_image = image if isinstance(image, Image) else None
        self.current_path = (
            Path(self.current_image.path) if self.current_image is not None else None
        )
        self.current_caption_path = None
        self.autosave_timer.stop()

        if self.current_path is None:
            self._replace_text("")
            self.path_label.setText("No media selected")
            self._set_status("")
            self._set_controls_enabled(False)
            return

        self._set_controls_enabled(True)
        draft = self._drafts.get(self.current_path)
        if draft is not None:
            self.current_caption_path = self._resolve_caption_path()
            self._replace_text(draft, dirty=True)
            self.path_label.setText(
                f"{self.current_caption_path} (unsaved draft)"
            )
            self._validate_editor_text()
            return
        self.reload_caption()

    def reload_caption(self):
        if self.current_path is None:
            return
        self._drafts.pop(self.current_path, None)
        self.autosave_timer.stop()
        preferred_path = ideogram_caption_path(self.current_path)
        if preferred_path.exists():
            self.current_caption_path = preferred_path
            try:
                raw_text = preferred_path.read_text(encoding="utf-8")
            except OSError as exc:
                self._replace_text("")
                self._set_status(f"Failed to read caption: {exc}", error=True)
                return
            self._replace_text(raw_text)
            self.path_label.setText(str(preferred_path))
            self._validate_editor_text()
            return

        try:
            caption = discover_ideogram_caption(self.current_path)
        except IdeogramCaptionError as exc:
            self.current_caption_path = preferred_path
            self._replace_text("")
            self.path_label.setText(str(preferred_path))
            self._set_status(str(exc), error=True)
            return

        if caption is None:
            self.current_caption_path = preferred_path
            self._replace_text("")
            self.path_label.setText(f"{preferred_path} (not created)")
            self._set_status("No Ideogram caption found.")
            return

        self.current_caption_path = caption.source_path
        try:
            raw_text = caption.source_path.read_text(encoding="utf-8")
        except OSError:
            raw_text = caption.to_json(pretty=True)
        self._replace_text(raw_text)
        self.path_label.setText(str(caption.source_path))
        self._set_status(
            f"Valid caption with {len(caption.elements)} element(s)."
        )

    def create_new_caption(self):
        if self.current_image is None:
            return
        if not self._confirm_replacement():
            return
        caption = self._empty_caption()
        self._replace_text(caption.to_json(pretty=True), dirty=True)
        self.current_caption_path = ideogram_caption_path(self.current_path)
        self.path_label.setText(str(self.current_caption_path))
        self.save_caption()

    def create_caption_from_markings(self):
        if self.current_image is None:
            return
        if not self._confirm_replacement():
            return
        dimensions = self.current_image.valid_dimensions()
        if dimensions is None:
            self._set_status(
                "Cannot convert markings without valid image dimensions.",
                error=True,
            )
            return
        image_width, image_height = dimensions
        elements = []
        for marking in self.current_image.markings:
            if marking.type == ImageMarking.CROP:
                continue
            rect = marking.rect.normalized()
            bbox = pixel_rect_to_bbox(
                rect.x(),
                rect.y(),
                rect.width(),
                rect.height(),
                image_width,
                image_height,
            )
            elements.append(
                IdeogramElement(
                    type="obj",
                    desc=str(marking.label or ""),
                    bbox=bbox,
                )
            )
        caption = self._empty_caption(elements=elements)
        self._replace_text(caption.to_json(pretty=True), dirty=True)
        self.current_caption_path = ideogram_caption_path(self.current_path)
        self.path_label.setText(str(self.current_caption_path))
        self.save_caption()

    def save_caption(self) -> bool:
        if self.current_path is None:
            return False
        try:
            caption = self._caption_from_editor()
            destination = save_ideogram_caption(
                self.current_path,
                caption,
                path=self.current_caption_path or ideogram_caption_path(
                    self.current_path
                ),
                pretty=self._editor_uses_pretty_json(),
            )
        except (IdeogramCaptionError, OSError, json.JSONDecodeError) as exc:
            self._set_status(f"Not saved: {exc}", error=True)
            return False

        self.current_caption_path = destination
        self._dirty = False
        self._drafts.pop(self.current_path, None)
        self.path_label.setText(str(destination))
        self._set_status(
            f"Saved valid caption with {len(caption.elements)} element(s).",
            success=True,
        )
        self.image_viewer.refresh_ideogram_caption_overlays()
        self.caption_saved.emit(destination)
        return True

    def format_caption(self):
        try:
            caption = self._caption_from_editor()
        except (IdeogramCaptionError, json.JSONDecodeError) as exc:
            self._set_status(f"Cannot format: {exc}", error=True)
            return
        self._replace_text(caption.to_json(pretty=True), dirty=True)
        self._set_status("Formatted. Waiting to autosave.", success=True)
        self.autosave_timer.start()

    def copy_caption(self):
        QApplication.clipboard().setText(self.editor.toPlainText())
        self._set_status("Caption copied to clipboard.", success=True)

    def _autosave_if_valid(self):
        if not self._dirty or self.current_path is None:
            return
        try:
            self._caption_from_editor()
        except (IdeogramCaptionError, json.JSONDecodeError):
            return
        self.save_caption()

    def _on_text_changed(self):
        if self._loading or self.current_path is None:
            return
        self._dirty = True
        self._drafts[self.current_path] = self.editor.toPlainText()
        if self._validate_editor_text():
            self._set_status("Valid JSON. Autosave pending.", success=True)
            self.autosave_timer.start()
        else:
            self.autosave_timer.stop()

    def _validate_editor_text(self) -> bool:
        if not self.editor.toPlainText().strip():
            self._set_status("No Ideogram caption found.")
            return False
        try:
            caption = self._caption_from_editor()
        except (IdeogramCaptionError, json.JSONDecodeError) as exc:
            self._set_status(f"Invalid draft: {exc}", error=True)
            return False
        self._set_status(
            f"Valid caption with {len(caption.elements)} element(s).",
            success=True,
        )
        return True

    def _caption_from_editor(self) -> IdeogramCaption:
        payload = json.loads(self.editor.toPlainText())
        if not isinstance(payload, dict):
            raise IdeogramCaptionError(
                "Ideogram caption root must be a JSON object."
            )
        return IdeogramCaption.from_dict(
            payload,
            source_path=self.current_caption_path,
        )

    def _empty_caption(
        self,
        *,
        elements: list[IdeogramElement] | None = None,
    ) -> IdeogramCaption:
        dimensions = self.current_image.valid_dimensions()
        aspect_ratio = None
        if dimensions is not None:
            width, height = dimensions
            divisor = _greatest_common_divisor(width, height)
            aspect_ratio = f"{width // divisor}:{height // divisor}"
        return IdeogramCaption(
            aspect_ratio=aspect_ratio,
            high_level_description="",
            compositional_background="",
            elements=list(elements or []),
        )

    def _resolve_caption_path(self) -> Path:
        try:
            caption = discover_ideogram_caption(self.current_path)
        except IdeogramCaptionError:
            caption = None
        if caption is not None and caption.source_path is not None:
            return caption.source_path
        return ideogram_caption_path(self.current_path)

    def _confirm_replacement(self) -> bool:
        if not self.editor.toPlainText().strip():
            return True
        reply = QMessageBox.question(
            self,
            "Replace Ideogram Caption",
            "Replace the current Ideogram caption content?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _editor_uses_pretty_json(self) -> bool:
        return "\n" in self.editor.toPlainText().strip()

    def _replace_text(self, text: str, *, dirty: bool = False):
        self._loading = True
        try:
            self.editor.setPlainText(text)
        finally:
            self._loading = False
        self._dirty = dirty

    def _set_controls_enabled(self, enabled: bool):
        self.editor.setEnabled(enabled)
        for button in (
            self.new_button,
            self.from_markings_button,
            self.save_button,
            self.reload_button,
            self.format_button,
            self.copy_button,
        ):
            button.setEnabled(enabled)

    def _set_status(
        self,
        text: str,
        *,
        error: bool = False,
        success: bool = False,
    ):
        color = "#FF6B6B" if error else "#68D391" if success else "#AAB2BD"
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(text)


def _greatest_common_divisor(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return max(1, abs(a))
