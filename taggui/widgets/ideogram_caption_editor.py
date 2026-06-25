"""Dock editor for Ideogram 4 structured caption sidecars."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QModelIndex, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from utils.ideogram_caption import (
    IdeogramCaption,
    IdeogramCaptionError,
    IdeogramElement,
    append_unique_elements,
    discover_ideogram_caption,
    ideogram_caption_path,
    pixel_rect_to_bbox,
    save_ideogram_caption,
)
from utils.image import Image, ImageMarking
from widgets.auto_captioner import InlineEditorResizeGrip


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
        self.path_label.setObjectName("ideogramCaptionFile")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.summary_label = QLabel("Select an image to inspect its caption.")
        self.summary_label.setObjectName("ideogramCaptionSummary")
        self.summary_label.setWordWrap(True)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("ideogramCaptionJson")
        self.editor.setPlaceholderText(
            "Select an image, then create or load an Ideogram 4 caption."
        )
        editor_font = QFont("DejaVu Sans Mono")
        editor_font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(editor_font)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setMinimumHeight(96)
        self.editor.setMaximumHeight(420)
        self.editor.setFixedHeight(210)
        self.editor.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.editor._inline_resize_grip = InlineEditorResizeGrip(
            self.editor,
            minimum_height=96,
            maximum_height=420,
        )

        self.status_label = QLabel()
        self.status_label.setObjectName("ideogramCaptionStatus")
        self.status_label.setWordWrap(True)

        self.from_markings_button = QPushButton("Add markings")
        self.from_markings_button.setObjectName("ideogramCaptionPrimaryButton")
        self.from_markings_button.setToolTip(
            "Add unique TagGUI hint/include/exclude markings as Ideogram "
            "elements. Crop markings are ignored."
        )

        self.json_toggle_button = QPushButton("JSON")
        self.json_toggle_button.setObjectName("ideogramCaptionSecondaryButton")
        self.json_toggle_button.setCheckable(True)
        self.json_toggle_button.setToolTip("Show or hide the raw structured JSON.")

        self.more_button = QToolButton()
        self.more_button.setObjectName("ideogramCaptionMoreButton")
        self.more_button.setText("More")
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        actions_menu = QMenu(self.more_button)
        self.new_action = actions_menu.addAction("New caption")
        self.save_action = actions_menu.addAction("Save now")
        self.reload_action = actions_menu.addAction("Reload from disk")
        actions_menu.addSeparator()
        self.format_action = actions_menu.addAction("Format JSON")
        self.copy_action = actions_menu.addAction("Copy JSON")
        self.paste_action = actions_menu.addAction("Paste JSON")
        self.more_button.setMenu(actions_menu)

        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        controls_layout.addWidget(self.from_markings_button, 1)
        controls_layout.addWidget(self.json_toggle_button)
        controls_layout.addWidget(self.more_button)

        self.json_container = QWidget()
        json_layout = QVBoxLayout(self.json_container)
        json_layout.setContentsMargins(0, 0, 0, 0)
        json_layout.setSpacing(4)
        json_header = QLabel("Structured JSON")
        json_header.setObjectName("ideogramCaptionSectionLabel")
        json_layout.addWidget(json_header)
        json_layout.addWidget(self.editor)
        self.json_container.hide()

        container = QWidget()
        container.setObjectName("ideogramCaptionRoot")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self.path_label)
        layout.addWidget(self.summary_label)
        layout.addLayout(controls_layout)
        layout.addWidget(self.json_container)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self.setWidget(container)
        self.setStyleSheet(
            """
            QWidget#ideogramCaptionRoot {
                background: #202326;
            }
            QLabel#ideogramCaptionFile {
                color: #f0f3f5;
                font-weight: 600;
                font-size: 13px;
            }
            QLabel#ideogramCaptionSummary {
                color: #aeb8c1;
                background: #292e33;
                border: 1px solid #343b42;
                border-radius: 6px;
                padding: 8px;
            }
            QLabel#ideogramCaptionSectionLabel {
                color: #8eddd4;
                font-weight: 600;
            }
            QPushButton#ideogramCaptionPrimaryButton {
                background: #247f78;
                border: 1px solid #339d94;
                border-radius: 6px;
                color: white;
                font-weight: 600;
                min-height: 28px;
                padding: 3px 10px;
            }
            QPushButton#ideogramCaptionPrimaryButton:hover {
                background: #2d9188;
            }
            QPushButton#ideogramCaptionSecondaryButton,
            QToolButton#ideogramCaptionMoreButton {
                background: #30363c;
                border: 1px solid #444d55;
                border-radius: 6px;
                color: #dbe2e8;
                min-height: 28px;
                padding: 3px 9px;
            }
            QPushButton#ideogramCaptionSecondaryButton:checked {
                border-color: #45b8ae;
                color: #8eddd4;
            }
            QPlainTextEdit#ideogramCaptionJson {
                background: #171a1d;
                border: 1px solid #3a4249;
                border-radius: 6px;
                color: #d9e2e8;
                padding: 6px;
                selection-background-color: #286f69;
            }
            """
        )

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(900)
        self.autosave_timer.timeout.connect(self._autosave_if_valid)

        self.editor.textChanged.connect(self._on_text_changed)
        self.from_markings_button.clicked.connect(
            self.create_caption_from_markings
        )
        self.json_toggle_button.toggled.connect(
            self.json_container.setVisible
        )
        self.new_action.triggered.connect(self.create_new_caption)
        self.save_action.triggered.connect(self.save_caption)
        self.reload_action.triggered.connect(self.reload_caption)
        self.format_action.triggered.connect(self.format_caption)
        self.copy_action.triggered.connect(self.copy_caption)
        self.paste_action.triggered.connect(self.paste_caption)
        self._set_controls_enabled(False)

    def load_image(self, index: QModelIndex):
        """Backward-compatible index loader."""
        image = (
            index.data(Qt.ItemDataRole.UserRole)
            if index is not None and index.isValid()
            else None
        )
        self.load_media(image)

    def load_media(self, image):
        """Load the displayed media item's caption or preserved draft."""
        if self.current_path is not None and self._dirty:
            self._drafts[self.current_path] = self.editor.toPlainText()

        self.current_image = image if isinstance(image, Image) else None
        self.current_path = (
            Path(self.current_image.path) if self.current_image is not None else None
        )
        self.current_caption_path = None
        self.autosave_timer.stop()

        if self.current_path is None:
            self._replace_text("")
            self.path_label.setText("No media selected")
            self.path_label.setToolTip("")
            self.summary_label.setText(
                "Select an image to inspect its caption."
            )
            self._set_status("")
            self._set_controls_enabled(False)
            return

        self._set_controls_enabled(True)
        self.path_label.setText(self.current_path.name)
        self.path_label.setToolTip(str(self.current_path))
        draft = self._drafts.get(self.current_path)
        if draft is not None:
            self.current_caption_path = self._resolve_caption_path()
            self._replace_text(draft, dirty=True)
            self.path_label.setText(f"{self.current_path.name}  •  draft")
            self._validate_editor_text()
            return
        self.reload_caption()

    def minimumSizeHint(self):
        return QSize(180, 112)

    def sizeHint(self):
        return QSize(300, 240)

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
                self._update_summary()
                return
            self._replace_text(raw_text)
            self.path_label.setText(self.current_path.name)
            self.path_label.setToolTip(str(preferred_path))
            self._validate_editor_text()
            return

        try:
            caption = discover_ideogram_caption(self.current_path)
        except IdeogramCaptionError as exc:
            self.current_caption_path = preferred_path
            self._replace_text("")
            self.path_label.setText(self.current_path.name)
            self.path_label.setToolTip(str(preferred_path))
            self._set_status(str(exc), error=True)
            self._update_summary(error=True)
            return

        if caption is None:
            self.current_caption_path = preferred_path
            self._replace_text("")
            self.path_label.setText(self.current_path.name)
            self.path_label.setToolTip(str(preferred_path))
            self._set_status("No Ideogram caption found.")
            self._update_summary()
            return

        self.current_caption_path = caption.source_path
        try:
            raw_text = caption.source_path.read_text(encoding="utf-8")
        except OSError:
            raw_text = caption.to_json(pretty=True)
        self._replace_text(raw_text)
        self.path_label.setText(self.current_path.name)
        self.path_label.setToolTip(str(caption.source_path))
        self._set_status(
            ""
        )
        self._update_summary(caption=caption)

    def create_new_caption(self):
        if self.current_image is None:
            return
        if not self._confirm_replacement():
            return
        caption = self._empty_caption()
        self._replace_text(caption.to_json(pretty=True), dirty=True)
        self.current_caption_path = ideogram_caption_path(self.current_path)
        self.path_label.setToolTip(str(self.current_caption_path))
        self.save_caption()

    def create_caption_from_markings(self):
        if self.current_image is None:
            return
        dimensions = self.current_image.valid_dimensions()
        if dimensions is None:
            self._set_status(
                "Cannot convert markings without valid image dimensions.",
                error=True,
            )
            return
        image_width, image_height = dimensions
        candidates = []
        markings = self._current_convertible_markings()
        if not markings:
            self._set_status(
                "No TagGUI hint/include/exclude markings were found. "
                "Crop boxes and Ideogram overlay boxes are not converted.",
                error=True,
            )
            return
        for marking in markings:
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
            candidates.append(
                IdeogramElement(
                    type="obj",
                    desc=self._marking_description(marking),
                    bbox=bbox,
                )
            )
        try:
            caption = self._caption_from_editor()
        except (IdeogramCaptionError, json.JSONDecodeError):
            caption = self._empty_caption()
        caption.elements, added_count = append_unique_elements(
            caption.elements,
            candidates,
        )
        skipped_count = len(candidates) - added_count
        if added_count == 0:
            self._set_status(
                f"No regions added; all {skipped_count} marking(s) already "
                "exist in the Ideogram caption.",
                success=True,
            )
            return
        self._replace_text(caption.to_json(pretty=True), dirty=True)
        self.current_caption_path = (
            self.current_caption_path
            or ideogram_caption_path(self.current_path)
        )
        self.path_label.setToolTip(str(self.current_caption_path))
        if self.save_caption():
            self._set_status(
                f"Added {added_count} region(s); skipped {skipped_count} "
                "existing duplicate(s).",
                success=True,
            )

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
        self.path_label.setText(self.current_path.name)
        self.path_label.setToolTip(str(destination))
        self._set_status(
            f"Saved valid caption with {len(caption.elements)} element(s).",
            success=True,
        )
        self._update_summary(caption=caption)
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

    def paste_caption(self):
        clipboard_text = QApplication.clipboard().text()
        if not clipboard_text.strip():
            self._set_status("Clipboard does not contain JSON.", error=True)
            return
        try:
            payload = json.loads(clipboard_text)
            if not isinstance(payload, dict):
                raise IdeogramCaptionError(
                    "Ideogram caption root must be a JSON object."
                )
            caption = IdeogramCaption.from_dict(
                payload,
                source_path=self.current_caption_path,
            )
        except (IdeogramCaptionError, json.JSONDecodeError) as exc:
            self._set_status(f"Clipboard JSON rejected: {exc}", error=True)
            return
        self._replace_text(caption.to_json(pretty=True), dirty=True)
        self.json_toggle_button.setChecked(True)
        self._update_summary(caption=caption, draft=True)
        self._set_status("Pasted valid JSON. Autosave pending.", success=True)
        self.autosave_timer.start()

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
            self._update_summary(error=True)
            return False
        if self._dirty:
            self._set_status("Valid JSON. Autosave pending.", success=True)
        else:
            self._set_status("")
        self._update_summary(caption=caption, draft=self._dirty)
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

    def _current_convertible_markings(self):
        """Prefer live viewer rectangles when they belong to the current image."""
        live_markings = []
        try:
            viewer_index = self.image_viewer.proxy_image_index
            viewer_image = viewer_index.data(Qt.ItemDataRole.UserRole)
            viewer_path = Path(viewer_image.path) if viewer_image is not None else None
            if viewer_path == self.current_path:
                for item in self.image_viewer.marking_items:
                    marking_type = getattr(item, "rect_type", ImageMarking.NONE)
                    if marking_type in {ImageMarking.CROP, ImageMarking.NONE}:
                        continue
                    label = str(item.data(0) or "")
                    try:
                        confidence = float(item.data(1))
                    except (TypeError, ValueError):
                        confidence = 1.0
                    live_markings.append(
                        _ConvertibleMarking(
                            label=label,
                            type=marking_type,
                            rect=item.rect().toRect(),
                            confidence=confidence,
                        )
                    )
        except (AttributeError, RuntimeError):
            live_markings = []
        if live_markings:
            return live_markings
        return [
            marking
            for marking in self.current_image.markings
            if marking.type not in {ImageMarking.CROP, ImageMarking.NONE}
        ]

    @staticmethod
    def _marking_description(marking) -> str:
        label = str(marking.label or "").strip()
        if label:
            return label
        return "region"

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
        self.from_markings_button.setEnabled(enabled)
        self.json_toggle_button.setEnabled(enabled)
        self.more_button.setEnabled(enabled)
        for action in (
            self.new_action,
            self.save_action,
            self.reload_action,
            self.format_action,
            self.copy_action,
            self.paste_action,
        ):
            action.setEnabled(enabled)

    def _update_summary(
        self,
        *,
        caption: IdeogramCaption | None = None,
        draft: bool = False,
        error: bool = False,
    ):
        if self.current_path is None:
            self.summary_label.setText(
                "Select an image to inspect its caption."
            )
            return
        if error:
            self.summary_label.setText(
                "Caption JSON needs attention. The file on disk was not "
                "overwritten."
            )
            return
        if caption is None:
            self.summary_label.setText(
                "No structured caption yet. Add current markings or create "
                "a blank caption from More."
            )
            return
        object_count = sum(
            element.type == "obj" for element in caption.elements
        )
        text_count = sum(
            element.type == "text" for element in caption.elements
        )
        state = "Unsaved draft" if draft else "Caption ready"
        self.summary_label.setText(
            f"{state}  •  {len(caption.elements)} elements  •  "
            f"{object_count} objects  •  {text_count} text"
        )

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
        self.status_label.setVisible(bool(text))


def _greatest_common_divisor(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return max(1, abs(a))


class _ConvertibleMarking:
    def __init__(self, *, label, type, rect, confidence):
        self.label = label
        self.type = type
        self.rect = rect
        self.confidence = confidence
