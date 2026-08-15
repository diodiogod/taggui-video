"""Keyboard-driven ordered tag review."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import os
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QObject,
    QItemSelectionModel,
    QTimer,
    QStringListModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from controllers.quick_sort_controller import (
    QuickSortController,
    QuickSortHistoryRecord,
    QuickSortHud,
    QuickSortQueueSnapshot,
)
from utils.quick_sort import QuickSortProfile, QuickSortValidationError
from utils.quick_tag import (
    QuickTagMapping,
    QuickTagProfile,
    QuickTagSessionStore,
    edit_ordered_tag,
    merge_ordered_tags,
    normalize_quick_tag_key,
)


@dataclass
class QuickTagHistoryRecord:
    index: int
    path: str
    old_tags: list[str]
    new_tags: list[str]
    label: str
    color: str
    kind: str = "tags"
    from_position: int | None = None
    to_position: int | None = None


class QuickTagHud(QuickSortHud):
    """Quick Sort's unobtrusive HUD with ordered clickable tag chips."""

    chip_clicked = Signal(int)
    edit_submitted = Signal(str)

    def __init__(self, viewport: QWidget):
        super().__init__(viewport)
        self._chip_frame = QFrame(viewport)
        self._chip_frame.setObjectName("quickTagPendingFrame")
        self._chip_layout = QHBoxLayout(self._chip_frame)
        self._chip_layout.setContentsMargins(8, 5, 8, 5)
        self._chip_layout.setSpacing(4)
        self._chip_frame.hide()
        self._existing_frame = QFrame(viewport)
        self._existing_frame.setObjectName("quickTagExistingFrame")
        self._existing_frame.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self._existing_layout = QHBoxLayout(self._existing_frame)
        self._existing_layout.setContentsMargins(9, 5, 9, 5)
        self._existing_label = QLabel(self._existing_frame)
        self._existing_label.setObjectName("quickTagExistingLabel")
        self._existing_label.setTextFormat(Qt.TextFormat.RichText)
        self._existing_label.setWordWrap(True)
        self._existing_label.setMinimumWidth(0)
        self._existing_layout.addWidget(self._existing_label)
        self._existing_frame.hide()
        self.editor = QLineEdit(viewport)
        self.editor.setObjectName("quickTagInlineEditor")
        self.editor.setPlaceholderText("Type a tag…")
        self.editor.setClearButtonEnabled(True)
        self.editor.returnPressed.connect(
            lambda: self.edit_submitted.emit(self.editor.text())
        )
        self.editor.hide()
        self._completer_model = QStringListModel(self.editor)
        self.completer = QCompleter(self._completer_model, self.editor)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.editor.setCompleter(self.completer)
        self._pending_tags: list[str] = []
        self._pending_colors: list[str] = []
        self._apply_style("#62E7D8")

    def _apply_style(self, accent: str):
        super()._apply_style(accent)
        if not hasattr(self, "_chip_frame"):
            return
        color = QColor(accent)
        if not color.isValid():
            color = QColor("#62E7D8")
        self._chip_frame.setStyleSheet(
            f"QFrame#quickTagPendingFrame {{ background: rgba(28,28,28,205); "
            f"border: 1px solid {color.name()}; border-radius: 7px; }}"
            "QFrame#quickTagExistingFrame { background: rgba(28,28,28,170); "
            "border: 1px solid rgba(112,112,112,105); border-radius: 7px; }"
            "QLabel#quickTagExistingLabel { color: #BDBDBD; font-size: 10px; }"
            f"QPushButton {{ color: #F0F0F0; background: rgba(65,65,65,210); "
            f"border: 1px solid rgba(150,150,150,130); border-radius: 5px; "
            f"padding: 4px 8px; font-weight: 650; }}"
            f"QPushButton:hover {{ background: {color.name()}; color: #101010; }}"
        )
        self.editor.setStyleSheet(
            f"QLineEdit#quickTagInlineEditor {{ background: rgba(25,25,25,235); "
            f"color: #F4F4F4; border: 2px solid {color.name()}; "
            "border-radius: 6px; padding: 5px 8px; }}"
        )

    def set_completion_tags(self, tags: list[str]):
        self._completer_model.setStringList(sorted(set(tags), key=str.casefold))

    def set_pending(
        self,
        tags: list[str],
        colors: list[str],
        selected_index: int = -1,
        *,
        reposition: bool = True,
    ):
        self._pending_tags = list(tags)
        self._pending_colors = list(colors)
        while self._chip_layout.count():
            item = self._chip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, tag in enumerate(self._pending_tags):
            button = QPushButton(f"{index + 1}. {tag}", self._chip_frame)
            button.setToolTip("Click to select this tag for editing or insertion")
            accent = self._pending_colors[index] if index < len(self._pending_colors) else "#62E7D8"
            button.setStyleSheet(
                f"QPushButton {{ border-left: 3px solid {accent}; }}"
                f"QPushButton:hover {{ background: {accent}; color: #101010; }}"
            )
            button.clicked.connect(lambda _checked=False, value=index: self.chip_clicked.emit(value))
            self._chip_layout.addWidget(button)
        self._chip_frame.setVisible(bool(self._pending_tags))
        self._chip_layout.invalidate()
        self._chip_layout.activate()
        if reposition:
            self.reposition()
        # deleteLater() removes the previous chip widgets after this call;
        # recalculate once more after Qt has processed those deletions so the
        # pending-tag frame cannot collapse until another key is pressed.
        if reposition:
            QTimer.singleShot(0, self.reposition)

    def set_existing(self, tags: list[str], *, reposition: bool = True):
        normalized = [str(tag).strip() for tag in tags if str(tag).strip()]
        if not normalized:
            self._existing_frame.hide()
            self._existing_label.clear()
            if reposition:
                self.reposition()
            return
        rendered = " · ".join(
            f'<span style="color:#D5D5D5">{html.escape(tag)}</span>'
            for tag in normalized
        )
        self._existing_label.setText(
            f'<span style="color:#9E9E9E;font-weight:650">Saved:</span> {rendered}'
        )
        self._existing_frame.show()
        if reposition:
            self.reposition()

    def begin_editor(self, text: str, *, accent: str, tags: list[str], insert: bool):
        self._apply_style(accent)
        self.set_completion_tags(tags)
        self.editor.setText(text)
        self.editor.setProperty("quick_tag_insert", bool(insert))
        self.editor.show()
        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self.editor.setCursorPosition(len(text))
        self.reposition()

    def end_editor(self):
        self.editor.hide()
        self.editor.clearFocus()

    def show(self):
        super().show()
        if hasattr(self, "_chip_frame"):
            self._chip_frame.show() if self._pending_tags else self._chip_frame.hide()
        if hasattr(self, "_existing_frame") and self._existing_label.text():
            self._existing_frame.show()
        self.reposition()

    def hide(self):
        if hasattr(self, "editor"):
            self.editor.hide()
        if hasattr(self, "_chip_frame"):
            self._chip_frame.hide()
        if hasattr(self, "_existing_frame"):
            self._existing_frame.hide()
        super().hide()

    def reposition(self):
        super().reposition()
        if not self.status_bar.isVisible():
            return
        bounds = self.viewport.rect()
        margin = max(6, min(14, (bounds.width() - 1) // 12))
        legend_top = self.legend.geometry().top()
        chip_width = min(max(220, bounds.width() - margin * 2), 760)
        self._chip_frame.setMaximumWidth(chip_width)
        self._chip_frame.adjustSize()
        above_top = legend_top
        if self._chip_frame.isVisible():
            chip_height = self._chip_frame.sizeHint().height()
            chip_top = max(margin, above_top - chip_height - 5)
            self._chip_frame.setGeometry(margin, chip_top, chip_width, chip_height)
            above_top = chip_top
        if self._existing_frame.isVisible():
            self._existing_frame.setMaximumWidth(chip_width)
            self._existing_label.setMaximumWidth(max(1, chip_width - 18))
            self._existing_frame.adjustSize()
            existing_height = self._existing_frame.sizeHint().height()
            existing_top = max(margin, above_top - existing_height - 5)
            self._existing_frame.setGeometry(
                margin,
                existing_top,
                chip_width,
                existing_height,
            )
            above_top = existing_top
        if self.editor.isVisible():
            editor_width = min(max(240, bounds.width() - margin * 2), 520)
            self.editor.setGeometry(
                margin,
                max(margin, above_top - 5 - self.editor.sizeHint().height()),
                editor_width,
                self.editor.sizeHint().height(),
            )
        self._chip_frame.raise_()
        self._existing_frame.raise_()
        self.editor.raise_()


class QuickTagController(QObject):
    """Own an immutable media queue and ordered, per-image tag edits."""

    active_changed = Signal(bool)
    readiness_changed = Signal(bool)
    session_finished = Signal(dict)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.sort_controller: QuickSortController = main_window.quick_sort_controller
        self.session_store = QuickTagSessionStore()
        self.hud = QuickTagHud(main_window.image_viewer.view.viewport())
        main_window.image_viewer._quick_tag_hud = self.hud
        self.hud.exit_requested.connect(self.finish_session)
        self.hud.start_fresh_requested.connect(self.restart_fresh_session)
        self.hud.fit_requested.connect(getattr(main_window.image_viewer, "zoom_fit", lambda: None))
        self.hud.original_size_requested.connect(getattr(main_window.image_viewer, "zoom_original", lambda: None))
        self.hud.chip_clicked.connect(self.select_pending_tag)
        self.hud.edit_submitted.connect(self._editor_submitted)
        self.profile: QuickTagProfile | None = None
        self.queue: QuickSortQueueSnapshot | None = None
        self.position = 0
        self._browser_context: dict | None = None
        self._queue_profile: QuickSortProfile | None = None
        self._saved_layout = False
        self._active = False
        self._pending_tags: list[str] = []
        self._pending_colors: list[str] = []
        self._existing_tags: list[str] = []
        self._pending_original_tags: list[str] | None = None
        self._selected_pending_index = -1
        self._editing_index = -1
        self._editing_insert = False
        self._decisions: dict[int, QuickTagHistoryRecord] = {}
        self._history: list[QuickTagHistoryRecord] = []
        self._history_cursor = 0
        self._missing: set[int] = set()
        self._session_key: str | None = None

    @property
    def active(self) -> bool:
        return self._active

    def _build_queue_profile(self, profile: QuickTagProfile) -> QuickSortProfile:
        return QuickSortProfile(
            name=f"Quick Tags: {profile.name}",
            source_scope=profile.source_scope,
            include_subfolders=profile.include_subfolders,
            include_videos=profile.include_videos,
            start_fullscreen=profile.start_fullscreen,
        )

    def estimate_queue_count(self, profile: QuickTagProfile, context: dict | None = None) -> int:
        return self.sort_controller.estimate_queue_count(
            self._build_queue_profile(profile),
            context or self.sort_controller.resolve_browser_context(),
        )

    def start_session(self, profile: QuickTagProfile) -> bool:
        if self.active or self.sort_controller.active:
            return False
        try:
            profile.validate()
            context = self.sort_controller.resolve_browser_context()
            queue_profile = self._build_queue_profile(profile)
            queue = self.sort_controller.build_queue(queue_profile, context)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.main_window, "Quick Tags", str(exc))
            return False
        if not len(queue):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self.main_window, "Quick Tags", "No media is available in the selected scope.")
            return False
        self.profile = profile
        self.queue = queue
        self._queue_profile = queue_profile
        self._browser_context = context
        self.sort_controller._browser_context = context
        self.sort_controller.profile = queue_profile
        try:
            self.sort_controller._enter_focused_layout()
            self._saved_layout = True
        except Exception as exc:
            try:
                self.sort_controller._restore_layout()
            except Exception:
                pass
            self.sort_controller._browser_context = None
            self.sort_controller.profile = None
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.main_window, "Quick Tags", f"Could not enter Quick Tag mode:\n\n{exc}")
            return False
        self.position = 0
        self._pending_tags.clear()
        self._pending_colors.clear()
        self._existing_tags.clear()
        self._pending_original_tags = None
        self._selected_pending_index = -1
        self._editing_index = -1
        self._decisions.clear()
        self._history.clear()
        self._history_cursor = 0
        self._missing.clear()
        self._session_key = self._make_session_key(profile, queue.directory_path)
        self._restore_session()
        # Activate before rendering the first item.  _show_current() and
        # _update_hud() intentionally no-op while inactive; setting this only
        # after the first render left the viewer open but the entire keyboard
        # workflow inert.
        self._active = True
        self._load_completion_tags()
        self.hud.show()
        self._show_current()
        self.active_changed.emit(True)
        return True

    def _make_session_key(self, profile: QuickTagProfile, directory: Path | None) -> str:
        raw = f"{profile.id}|{os.path.normcase(str(directory or ''))}|{profile.source_scope}|{profile.include_subfolders}|{profile.include_videos}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load_completion_tags(self):
        tags: list[str] = []
        model = (self._browser_context or {}).get("model")
        database = getattr(model, "_db", None)
        if database is not None:
            try:
                tags = [str(item.get("tag")) for item in database.get_all_tags() if item.get("tag")]
            except Exception:
                tags = []
        self.hud.set_completion_tags(tags)

    def _restore_session(self):
        if not self._session_key or self.queue is None:
            return
        state = self.session_store.get(self._session_key) or {}
        saved = state.get("items", [])
        positions = {
            os.path.normcase(str(self.sort_controller._absolute_path(path))).casefold(): index
            for index, path in enumerate(self.queue.paths)
        } if self.queue.paths else {}
        id_positions = {
            int(image_id): index
            for index, image_id in enumerate(self.queue.image_ids)
        } if self.queue.image_ids else {}
        for item in saved if isinstance(saved, list) else []:
            if not isinstance(item, dict):
                continue
            index = positions.get(
                os.path.normcase(
                    str(self.sort_controller._absolute_path(item.get("path", "")))
                ).casefold()
            )
            if index is None and id_positions and self.queue.database is not None:
                try:
                    relative = str(
                        self.sort_controller._absolute_path(item.get("path", ""))
                        .relative_to(self.queue.directory_path)
                    )
                    image_id = self.queue.database.get_image_id(relative)
                    index = id_positions.get(int(image_id)) if image_id is not None else None
                except Exception:
                    index = None
            if index is not None:
                self._decisions[index] = QuickTagHistoryRecord(
                    index=index,
                    path=str(item.get("path")),
                    old_tags=[],
                    new_tags=[],
                    label="Remembered tags",
                    color="#62E7D8",
                )

    def _persist_session(self):
        if not self._session_key or self.queue is None:
            return
        items = [{"path": record.path} for record in self._decisions.values()]
        try:
            if items:
                self.session_store.put(self._session_key, {"items": items})
            else:
                self.session_store.remove(self._session_key)
        except OSError:
            pass

    def _append_history(self, record: QuickTagHistoryRecord):
        """Append an action, discarding the redo branch after a new action."""
        self._history = self._history[: self._history_cursor]
        self._history.append(record)
        self._history_cursor = len(self._history)

    def _record_navigation(self, from_position: int, to_position: int):
        """Make movement independently undoable from tag mutations."""
        if int(from_position) == int(to_position):
            return
        self._append_history(
            QuickTagHistoryRecord(
                index=-1,
                path="",
                old_tags=[],
                new_tags=[],
                label="Return to previous image",
                color="#93A5B4",
                kind="navigation",
                from_position=int(from_position),
                to_position=int(to_position),
            )
        )

    def _rebuild_decision(self, index: int):
        """Recompute the committed state after undoing/redoing one tag action."""
        for record in reversed(self._history[: self._history_cursor]):
            if record.kind in {"tags", "decision"} and record.index == index:
                self._decisions[index] = record
                return
        self._decisions.pop(index, None)

    def _current_path(self) -> Path | None:
        return self.queue.path_at(self.position) if self.queue is not None else None

    def _tags_for_path(self, path: Path) -> tuple[list[str], object | None, object | None]:
        context = self._browser_context or self.sort_controller.resolve_browser_context()
        model = context["model"]
        try:
            row = model.get_index_for_path(path)
            if row >= 0:
                index = model.index(row, 0)
                image = model.data(index, Qt.ItemDataRole.UserRole)
                if image is not None and hasattr(image, "tags"):
                    return [str(tag) for tag in image.tags if str(tag) != "__no_tags__"], image, index
        except Exception:
            pass
        database = getattr(model, "_db", None)
        if database is not None:
            try:
                root = getattr(model, "_directory_path", None)
                relative = str(path.relative_to(root)) if root else path.name
                image_id = database.get_image_id(relative)
                if image_id is not None:
                    return list(database.get_tags_for_image(image_id)), None, None
            except Exception:
                pass
        return [], None, None

    def _write_tags(self, path: Path, tags: list[str], image=None, index=None):
        context = self._browser_context or self.sort_controller.resolve_browser_context()
        model = context["model"]
        if image is not None and index is not None:
            model.update_image_tags(index, list(tags))
            return
        path.with_suffix(".txt").write_text(model.tag_separator.join(tags), encoding="utf-8")
        root = getattr(model, "_directory_path", None)
        sync = getattr(model, "_sync_paginated_db_tags_for_rel_path", None)
        if callable(sync) and root is not None:
            sync(str(path.relative_to(root)), list(tags), txt_path=path.with_suffix(".txt"))

    def _show_current(self, *, allow_decided: bool = False):
        if not self.active or self.queue is None:
            return
        total = len(self.queue)
        if allow_decided and 0 <= self.position < total:
            path = self._current_path()
            if path is not None and path.exists() and self.sort_controller._select_media_by_path(path):
                self._existing_tags = self._tags_for_path(path)[0]
                self._pending_tags.clear()
                self._pending_colors.clear()
                self._pending_original_tags = None
                self._selected_pending_index = -1
                self._update_hud()
                return
        while self.position < total:
            if self.position in self._decisions or self.position in self._missing:
                self.position += 1
                continue
            path = self._current_path()
            if path is not None and path.exists() and self.sort_controller._select_media_by_path(path):
                self._existing_tags = self._tags_for_path(path)[0]
                self._pending_tags.clear()
                self._pending_colors.clear()
                self._pending_original_tags = None
                self._selected_pending_index = -1
                self._update_hud()
                return
            self._missing.add(self.position)
            self.position += 1
        self._show_completion()

    def _update_hud(self):
        if not self.profile or not self.active:
            return
        mappings = self.profile.enabled_mappings()
        total = len(self.queue) if self.queue is not None else 0
        current = min(total, max(1, self.position + 1))
        self.hud.set_state(
            stage="Press tag keys · Tab refine · Shift+Tab insert · Space save / next",
            progress=f"{current:,} / {total:,}",
            mappings=[self._mapping_as_sort(mapping) for mapping in mappings],
            standard_keys=False,
            control_text=(
                '<span style="color:#A0A0A0;font-size:10px">'
                'Tab refine · Shift+Tab insert · Backspace remove · '
                'Space save / next · Arrows browse · Ctrl+Z return / undo one tag · Esc exit</span>'
            ),
        )
        self.hud.set_existing(self._existing_tags, reposition=False)
        self.hud.set_pending(
            self._pending_tags,
            self._pending_colors,
            self._selected_pending_index,
        )

    @staticmethod
    def _mapping_as_sort(mapping: QuickTagMapping):
        from utils.quick_sort import QuickSortMapping
        return QuickSortMapping(name=mapping.tag, key=mapping.key, folder=mapping.tag, color=mapping.color)

    def _ensure_pending_original(self) -> bool:
        if self._pending_original_tags is not None:
            return True
        path = self._current_path()
        if path is None:
            return False
        self._pending_original_tags = self._tags_for_path(path)[0]
        return True

    def add_mapping(self, mapping: QuickTagMapping):
        if not self._ensure_pending_original():
            return
        if mapping.tag in self._pending_tags or mapping.tag in (self._pending_original_tags or []):
            self.hud.show_feedback("ALREADY PRESENT", mapping.tag, mapping.color)
            return
        self._pending_tags.append(mapping.tag)
        self._pending_colors.append(mapping.color)
        self._selected_pending_index = len(self._pending_tags) - 1
        self._update_hud()

    def select_pending_tag(self, index: int):
        if 0 <= int(index) < len(self._pending_tags):
            self._selected_pending_index = int(index)
            self._update_hud()

    def _begin_editor(self, *, insert: bool):
        if not self._ensure_pending_original():
            return
        if insert:
            self._editing_index = max(0, self._selected_pending_index + 1)
            initial = ""
            accent = "#62E7D8"
        else:
            if not self._pending_tags:
                self.hud.show_feedback("NO TAG TO EDIT", "Choose a tag first", "#F2C96D")
                return
            self._editing_index = self._selected_pending_index if self._selected_pending_index >= 0 else len(self._pending_tags) - 1
            initial = self._pending_tags[self._editing_index]
            accent = self._pending_colors[self._editing_index]
        self._editing_insert = bool(insert)
        self.hud.begin_editor(initial, accent=accent, tags=self._completion_tags(), insert=insert)

    def _completion_tags(self) -> list[str]:
        return list(self.hud._completer_model.stringList())

    def _editor_submitted(self, text: str):
        value = " ".join(str(text or "").strip().split())
        if not value:
            self.hud.end_editor()
            self._editing_index = -1
            self._editing_insert = False
            return
        self._pending_tags = edit_ordered_tag(
            self._pending_tags,
            self._editing_index,
            value,
            insert=self._editing_insert,
        )
        if self._editing_insert:
            self._pending_colors.insert(self._editing_index, "#62E7D8")
        self._selected_pending_index = self._editing_index
        self.hud.end_editor()
        self._editing_index = -1
        self._editing_insert = False
        self._update_hud()

    def _remove_pending(self):
        if not self._pending_tags:
            return
        index = self._selected_pending_index if self._selected_pending_index >= 0 else len(self._pending_tags) - 1
        self._pending_tags.pop(index)
        self._pending_colors.pop(index)
        self._selected_pending_index = min(index - 1, len(self._pending_tags) - 1)
        self._update_hud()

    def _commit_current(self):
        path = self._current_path()
        if path is None:
            return False
        old_tags, image, index = self._tags_for_path(path)
        if not self._pending_tags:
            record = QuickTagHistoryRecord(
                self.position,
                str(path),
                list(old_tags),
                list(old_tags),
                "Skipped",
                "#93A5B4",
                kind="decision",
            )
            self._append_history(record)
            self._rebuild_decision(self.position)
            self._persist_session()
            self.hud.show_feedback("SKIPPED", "No tags added", "#93A5B4")
            return True

        new_tags = merge_ordered_tags(old_tags, self._pending_tags)
        if new_tags != old_tags:
            self._write_tags(path, new_tags, image, index)

        # Keep each newly-added tag as its own undoable action.  The file is
        # still written once, but Ctrl+Z can now remove the tags one by one.
        working_tags = list(old_tags)
        tag_records: list[QuickTagHistoryRecord] = []
        for tag, color in zip(self._pending_tags, self._pending_colors):
            next_tags = merge_ordered_tags(working_tags, [tag])
            if next_tags == working_tags:
                continue
            tag_records.append(
                QuickTagHistoryRecord(
                    self.position,
                    str(path),
                    list(working_tags),
                    list(next_tags),
                    str(tag),
                    str(color or "#62E7D8"),
                    kind="tags",
                )
            )
            working_tags = next_tags

        if tag_records:
            self._history = self._history[: self._history_cursor]
            self._history.extend(tag_records)
            self._history_cursor = len(self._history)
            label = ", ".join(record.label for record in tag_records)
            feedback_color = tag_records[-1].color
        else:
            record = QuickTagHistoryRecord(
                self.position,
                str(path),
                list(old_tags),
                list(old_tags),
                "Already present",
                self._pending_colors[-1] if self._pending_colors else "#62E7D8",
                kind="decision",
            )
            self._append_history(record)
            label = ", ".join(self._pending_tags)
            feedback_color = record.color
        self._rebuild_decision(self.position)
        self._persist_session()
        self.hud.show_feedback("TAGS SAVED", label, feedback_color)
        return True

    def _show_completion(self):
        if self.queue is None:
            return
        self._existing_tags.clear()
        self.hud.set_existing([])
        changed = len(
            [record for record in self._decisions.values() if record.new_tags != record.old_tags]
        )
        skipped = len(self._decisions) - changed + len(self._missing)
        self.hud.set_state(
            stage="Quick Tag Review complete",
            progress=f"{len(self.queue):,} / {len(self.queue):,}",
            mappings=[],
        )
        details = []
        if changed:
            details.append(f"{changed:,} images tagged")
        if skipped:
            details.append(f"{skipped:,} skipped")
        self.hud.show_feedback(
            "TAG REVIEW COMPLETE",
            " · ".join(details) or "No tags changed",
            "#62E7D8",
            action_text="Start fresh",
            persistent=True,
        )

    def advance(self):
        if not self.active or self.hud.editor.isVisible():
            return
        from_position = self.position
        if self.position in self._decisions and not self._pending_tags:
            self.position += 1
            self._show_current()
            self._record_navigation(from_position, self.position)
            return
        if not self._commit_current():
            return
        self.position += 1
        self._show_current()
        self._record_navigation(from_position, self.position)

    def browse(self, delta: int):
        """Move through the immutable queue without recording a tag decision."""
        if not self.active or self.hud.editor.isVisible() or self.queue is None:
            return
        if self._pending_tags:
            self.hud.show_feedback(
                "TAGS NOT SAVED",
                "Press Space to save, or Backspace to clear them before browsing",
                "#F2C96D",
            )
            return
        total = len(self.queue)
        if total <= 0:
            return
        step = 1 if int(delta) >= 0 else -1
        target = (
            total - 1 if step < 0 else total
        ) if self.position >= total else self.position + step
        while 0 <= target < total:
            path = self.queue.path_at(target)
            if (
                path is not None
                and path.exists()
                and self.sort_controller._select_media_by_path(path)
            ):
                from_position = self.position
                self.position = target
                self._existing_tags = self._tags_for_path(path)[0]
                self._pending_tags.clear()
                self._pending_colors.clear()
                self._pending_original_tags = None
                self._selected_pending_index = -1
                self.hud.feedback_animation.stop()
                self.hud.feedback.hide()
                self.hud.feedback_action.hide()
                self._update_hud()
                self._record_navigation(from_position, target)
                return
            target += step
        self.hud.show_feedback(
            "END OF REVIEW" if step > 0 else "START OF REVIEW",
            "No more images in this direction",
            "#93A5B4",
        )

    def undo(self):
        if not self.active or self._history_cursor <= 0:
            return
        if self._pending_tags:
            self.hud.show_feedback(
                "TAGS NOT SAVED",
                "Press Space to save, or Backspace to clear them first",
                "#F2C96D",
            )
            return
        record = self._history[self._history_cursor - 1]
        self._history_cursor -= 1
        if record.kind == "navigation":
            if record.from_position is not None:
                self.position = max(0, int(record.from_position))
            self._persist_session()
            self.hud.show_feedback("RETURNED", "Previous image", "#93A5B4")
            self._show_current(allow_decided=True)
            return
        path = Path(record.path)
        if path.exists():
            old_tags, image, index = self._tags_for_path(path)
            self._write_tags(path, record.old_tags, image, index)
        self._rebuild_decision(record.index)
        self._persist_session()
        self.hud.show_feedback("UNDONE", record.label, "#F2C96D")
        self._show_current(allow_decided=True)

    def redo(self):
        if not self.active or self._history_cursor >= len(self._history):
            return
        if self._pending_tags:
            self.hud.show_feedback(
                "TAGS NOT SAVED",
                "Press Space to save, or Backspace to clear them first",
                "#F2C96D",
            )
            return
        record = self._history[self._history_cursor]
        self._history_cursor += 1
        if record.kind == "navigation":
            if record.to_position is not None:
                self.position = max(0, int(record.to_position))
            self._persist_session()
            self.hud.show_feedback("MOVED FORWARD", "Next image", "#93A5B4")
            self._show_current(allow_decided=True)
            return
        path = Path(record.path)
        if path.exists():
            old_tags, image, index = self._tags_for_path(path)
            self._write_tags(path, record.new_tags, image, index)
        self._rebuild_decision(record.index)
        self._persist_session()
        self.hud.show_feedback("REDONE", record.label, record.color)
        self._show_current(allow_decided=True)

    def handle_key_event(self, event, event_type) -> bool:
        if not self.active:
            return False
        if self.hud.editor.isVisible():
            if event_type == QEvent.Type.ShortcutOverride:
                if event.key() in {
                    Qt.Key.Key_Escape,
                    Qt.Key.Key_Return,
                    Qt.Key.Key_Enter,
                    Qt.Key.Key_Up,
                    Qt.Key.Key_Down,
                }:
                    event.accept()
                    return True
                return False
            if event_type != QEvent.Type.KeyPress:
                return False
            if event.key() == Qt.Key.Key_Escape:
                self.hud.end_editor()
                self._editing_index = -1
                self._editing_insert = False
                return True
            if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
                popup = self.hud.editor.completer().popup()
                if popup is not None and popup.isVisible():
                    return False
                # Keep the requested quick-edit aliases in addition to the
                # standard Home/End keys: Down goes to the beginning and Up
                # goes to the end of the single-line tag.
                self.hud.editor.setCursorPosition(
                    0 if event.key() == Qt.Key.Key_Down else len(self.hud.editor.text())
                )
                return True
            return False
        if event_type == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if event_type != QEvent.Type.KeyPress:
            return False
        event.accept()
        if event.isAutoRepeat():
            return True
        key = event.key()
        modifiers = event.modifiers()
        sequence = normalize_quick_tag_key(
            QKeySequence(event.keyCombination()).toString(
                QKeySequence.SequenceFormat.PortableText
            )
        )
        refine = normalize_quick_tag_key(self.profile.refine_key) if self.profile else "Tab"
        insert = normalize_quick_tag_key(self.profile.insert_key) if self.profile else "Shift+Tab"
        remove = normalize_quick_tag_key(self.profile.remove_key) if self.profile else "Backspace"
        advance = normalize_quick_tag_key(self.profile.advance_key) if self.profile else "Space"
        if sequence.casefold() == "esc" and modifiers == Qt.KeyboardModifier.NoModifier:
            self.finish_session()
            return True
        if sequence.casefold() == refine.casefold():
            self._begin_editor(insert=False)
            return True
        if sequence.casefold() == insert.casefold():
            self._begin_editor(insert=True)
            return True
        if sequence.casefold() == remove.casefold() and modifiers == Qt.KeyboardModifier.NoModifier:
            self._remove_pending()
            return True
        if sequence.casefold() == advance.casefold() and modifiers == Qt.KeyboardModifier.NoModifier:
            self.advance()
            return True
        if modifiers == Qt.KeyboardModifier.NoModifier and key in {
            Qt.Key.Key_Right,
            Qt.Key.Key_Down,
            Qt.Key.Key_PageDown,
        }:
            self.browse(1)
            return True
        if modifiers == Qt.KeyboardModifier.NoModifier and key in {
            Qt.Key.Key_Left,
            Qt.Key.Key_Up,
            Qt.Key.Key_PageUp,
        }:
            self.browse(-1)
            return True
        if key == Qt.Key.Key_F11 and modifiers == Qt.KeyboardModifier.NoModifier:
            self.sort_controller.toggle_fullscreen()
            return True
        if key == Qt.Key.Key_Z and modifiers == Qt.KeyboardModifier.ControlModifier:
            self.undo()
            return True
        if (key == Qt.Key.Key_Y and modifiers == Qt.KeyboardModifier.ControlModifier) or (
            key == Qt.Key.Key_Z and modifiers == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        ):
            self.redo()
            return True
        mapping = self.profile.mapping_for_key(sequence) if self.profile else None
        if mapping is not None:
            self.add_mapping(mapping)
        else:
            self.hud.show_feedback("UNASSIGNED KEY", sequence, "#93A5B4")
        return True

    def finish_session(self, *, reload_browser: bool = False):
        if not self.active:
            return
        summary = {
            "total": len(self.queue or ()),
            "changed": len([record for record in self._decisions.values() if record.new_tags != record.old_tags]),
            "skipped": len([record for record in self._decisions.values() if record.new_tags == record.old_tags]),
            "remaining": max(0, len(self.queue or ()) - len(self._decisions) - len(self._missing)),
        }
        self.hud.hide()
        if self._saved_layout:
            try:
                self.sort_controller._restore_layout()
            except Exception:
                pass
        self.sort_controller._browser_context = None
        self.sort_controller.profile = None
        self.sort_controller._saved_layout = None
        self._saved_layout = False
        self._active = False
        self.profile = None
        self.queue = None
        self._browser_context = None
        self._queue_profile = None
        self.active_changed.emit(False)
        self.session_finished.emit(summary)

    def restart_fresh_session(self):
        if not self.active or self.profile is None:
            return
        profile = self.profile
        if self._session_key:
            try:
                self.session_store.remove(self._session_key)
            except OSError:
                pass
        self._decisions.clear()
        self._history.clear()
        self._history_cursor = 0
        self._missing.clear()
        self._pending_tags.clear()
        self._pending_colors.clear()
        self._existing_tags.clear()
        self.position = 0
        self._show_current()
