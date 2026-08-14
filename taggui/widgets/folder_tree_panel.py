"""Explicitly refreshed folder hierarchy and reversible folder operations."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QSize, Qt, Signal
from PySide6.QtGui import QAction, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QDockWidget,
)

from utils.image_index_db import ImageIndexDB


def _absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _within(path: Path, root: Path) -> bool:
    try:
        _absolute(path).relative_to(_absolute(root))
        return True
    except ValueError:
        return False


@dataclass
class FolderHistoryEntry:
    action: str
    source: Path
    destination: Path
    created_at_ns: int


class FolderHistory:
    """Small history provider consumed by TagGUI's unified undo/redo menu."""

    def __init__(self, panel: "FolderTreePanel"):
        self.panel = panel
        self.undo_stack: list[FolderHistoryEntry] = []
        self.redo_stack: list[FolderHistoryEntry] = []

    def record(self, entry: FolderHistoryEntry):
        manager = getattr(self.panel.main_window, "menu_manager", None)
        if manager is not None:
            manager._clear_unified_redo_histories()
        self.undo_stack.append(entry)
        self.redo_stack.clear()
        self.panel._history_changed()

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def undo_timestamp(self) -> int:
        return self.undo_stack[-1].created_at_ns if self.undo_stack else 0

    def redo_timestamp(self) -> int:
        return self.redo_stack[-1].created_at_ns if self.redo_stack else 0

    def undo_action_name(self) -> str:
        return self.undo_stack[-1].action if self.undo_stack else "Folder change"

    def redo_action_name(self) -> str:
        return self.redo_stack[-1].action if self.redo_stack else "Folder change"

    def clear_redo(self):
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return
        entry = self.undo_stack[-1]
        if self.panel._apply_history_entry(entry, reverse=True):
            self.undo_stack.pop()
            self.redo_stack.append(entry)
            self.panel._history_changed()

    def redo(self):
        if not self.redo_stack:
            return
        entry = self.redo_stack[-1]
        if self.panel._apply_history_entry(entry, reverse=False):
            self.redo_stack.pop()
            self.undo_stack.append(entry)
            self.panel._history_changed()


class FolderTreeWidget(QTreeWidget):
    """Folder tree with hierarchy guides and filesystem-move drop routing."""

    folder_move_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        color = self.palette().color(QPalette.ColorRole.Text)
        color.setAlpha(210)
        painter.setPen(QPen(color, 1))
        indentation = max(12, self.indentation())

        def depth(item: QTreeWidgetItem) -> int:
            value = 0
            parent = item.parent()
            while parent is not None:
                value += 1
                parent = parent.parent()
            return value

        for parent in self._visible_items():
            if not parent.isExpanded() or parent.childCount() == 0:
                continue
            visible_children = [
                parent.child(index)
                for index in range(parent.childCount())
                if not parent.child(index).isHidden()
                and self.visualItemRect(parent.child(index)).isValid()
            ]
            if not visible_children:
                continue
            parent_rect = self.visualItemRect(parent)
            child_depth = depth(visible_children[0])
            guide_x = child_depth * indentation - indentation // 2
            first_rect = self.visualItemRect(visible_children[0])
            last_rect = self.visualItemRect(visible_children[-1])
            start_y = min(parent_rect.center().y(), first_rect.center().y())
            painter.drawLine(guide_x, start_y, guide_x, last_rect.center().y())
            for child in visible_children:
                child_rect = self.visualItemRect(child)
                painter.drawLine(
                    guide_x,
                    child_rect.center().y(),
                    guide_x + indentation // 2 - 2,
                    child_rect.center().y(),
                )
        painter.end()

    def _visible_items(self):
        item = self.topLevelItem(0)
        while item is not None:
            if self.visualItemRect(item).isValid():
                yield item
            item = self.itemBelow(item)

    def dropEvent(self, event):
        source_item = self.currentItem()
        target_item = self.itemAt(event.position().toPoint())
        if source_item is None or target_item is None or source_item is target_item:
            event.ignore()
            return
        source_path = source_item.data(0, Qt.ItemDataRole.UserRole)
        position = self.dropIndicatorPosition()
        if position == QAbstractItemView.DropIndicatorPosition.OnItem:
            parent_item = target_item
        else:
            parent_item = target_item.parent()
        parent_path = (
            parent_item.data(0, Qt.ItemDataRole.UserRole)
            if parent_item is not None
            else None
        )
        if not source_path or not parent_path:
            event.ignore()
            return
        event.acceptProposedAction()
        self.folder_move_requested.emit(str(source_path), str(parent_path))

class FolderTreePanel(QDockWidget):
    """Snapshot folder tree; it never installs a filesystem watcher."""

    root_changed = Signal(str)

    PATH_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, main_window):
        super().__init__("Folders", main_window)
        self.main_window = main_window
        self.setObjectName("folder_tree_panel")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.root_path: Path | None = None
        self.history = FolderHistory(self)
        self._build_ui()

    def _build_ui(self):
        root = QWidget(self)
        root.setMinimumWidth(0)
        root.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Refresh the folder hierarchy (F5 while this panel is focused)")
        self.add_button = QPushButton("+")
        self.add_button.setToolTip("Create a folder inside the selected folder")
        self.rename_button = QPushButton("Rename")
        self.move_button = QPushButton("Move")
        self.delete_button = QPushButton("×")
        self.delete_button.setToolTip("Delete the selected folder if it is empty")
        for button in (
            self.refresh_button,
            self.add_button,
            self.rename_button,
            self.move_button,
            self.delete_button,
        ):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            actions.addWidget(button)
        layout.addLayout(actions)

        self.tree = FolderTreeWidget()
        self.tree.setHeaderLabels(["Folder", "Media"])
        self.tree.setMinimumWidth(0)
        self.tree.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, 1)

        self.sort_button = QPushButton("Use selected folder for Quick Sort")
        self.sort_button.setToolTip(
            "Open this folder in the active browser and prepare Quick Sort with Current folder scope"
        )
        layout.addWidget(self.sort_button)
        self.setWidget(root)

        self.refresh_button.clicked.connect(lambda: self.refresh())
        self.add_button.clicked.connect(self.create_folder)
        self.rename_button.clicked.connect(self.rename_folder)
        self.move_button.clicked.connect(self.move_folder)
        self.delete_button.clicked.connect(self.delete_folder)
        self.sort_button.clicked.connect(self.use_for_quick_sort)
        self.tree.itemDoubleClicked.connect(lambda *_: self.open_selected_folder())
        self.tree.itemSelectionChanged.connect(self._update_actions)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.folder_move_requested.connect(self._move_folder_from_drop)
        refresh_action = QAction(self)
        refresh_action.setShortcut("F5")
        refresh_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        refresh_action.triggered.connect(lambda: self.refresh())
        self.addAction(refresh_action)
        self._update_actions()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 275
        very_compact = self.width() < 185
        self.refresh_button.setText("↻" if compact else "Refresh")
        self.rename_button.setText("✎" if compact else "Rename")
        self.move_button.setText("→" if compact else "Move")
        self.rename_button.setVisible(not very_compact)
        self.move_button.setVisible(not very_compact)
        self.sort_button.setText("Quick Sort" if compact else "Use selected folder for Quick Sort")

    def set_root(self, path: Path | str | None, *, force: bool = False):
        if path is None:
            self.root_path = None
            self.tree.clear()
            self._update_actions()
            return
        candidate = _absolute(path)
        if not force and self.root_path is not None and _within(candidate, self.root_path):
            self.select_path(candidate)
            return
        self.root_path = candidate
        self.refresh(select_path=candidate)
        self.root_changed.emit(str(candidate))

    def refresh(self, *, select_path: Path | None = None):
        root = self.root_path
        if root is None or not root.is_dir():
            self.tree.clear()
            self._update_actions()
            return
        selected = select_path or self.selected_path()
        expanded = {
            str(self._item_path(item))
            for item in self._walk_items()
            if item.isExpanded() and self._item_path(item) is not None
        }
        counts: dict[str, int] = {}
        database = ImageIndexDB(root)
        try:
            indexed_paths = database.get_all_paths()
        finally:
            database.close()
        for indexed_path in indexed_paths:
            relative_parent = Path(str(indexed_path)).parent
            current = root
            counts[os.path.normcase(str(current))] = counts.get(
                os.path.normcase(str(current)), 0
            ) + 1
            for part in relative_parent.parts:
                if part in ("", "."):
                    continue
                current = current / part
                key = os.path.normcase(str(current))
                counts[key] = counts.get(key, 0) + 1
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()

        def add_directory(path: Path, parent: QTreeWidgetItem | None) -> tuple[QTreeWidgetItem, int]:
            item = QTreeWidgetItem([path.name or str(path), "0"])
            item.setData(0, self.PATH_ROLE, str(path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
            if parent is None:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            children: list[Path] = []
            try:
                for entry in os.scandir(path):
                    if entry.name in ImageIndexDB.INTERNAL_DIR_NAMES:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        children.append(Path(entry.path))
            except OSError:
                item.setDisabled(True)
            total = counts.get(os.path.normcase(str(path)), 0)
            for child in sorted(children, key=lambda value: value.name.casefold()):
                add_directory(child, item)
            item.setText(1, str(total))
            item.setToolTip(0, str(path))
            item.setExpanded(str(path) in expanded or parent is None)
            return item, total

        add_directory(root, None)
        self.tree.setUpdatesEnabled(True)
        self.select_path(selected or root)
        self._update_actions()

    def _walk_items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))

    def _item_path(self, item: QTreeWidgetItem | None) -> Path | None:
        value = item.data(0, self.PATH_ROLE) if item is not None else None
        return _absolute(value) if value else None

    def selected_path(self) -> Path | None:
        return self._item_path(self.tree.currentItem())

    def select_path(self, path: Path | str | None):
        if path is None:
            return
        target = os.path.normcase(str(_absolute(path)))
        for item in self._walk_items():
            item_path = self._item_path(item)
            if item_path is not None and os.path.normcase(str(item_path)) == target:
                self.tree.setCurrentItem(item)
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.tree.scrollToItem(item)
                return

    def _update_actions(self):
        selected = self.selected_path()
        editable = selected is not None and self.root_path is not None and selected != self.root_path
        self.add_button.setEnabled(selected is not None)
        self.rename_button.setEnabled(editable)
        self.move_button.setEnabled(editable)
        self.delete_button.setEnabled(editable)
        self.sort_button.setEnabled(selected is not None)

    def _show_context_menu(self, point):
        item = self.tree.itemAt(point)
        if item is not None:
            self.tree.setCurrentItem(item)
        menu = QMenu(self.tree)
        menu.addAction("Open folder", self.open_selected_folder)
        menu.addAction("Use for Quick Sort", self.use_for_quick_sort)
        menu.addSeparator()
        menu.addAction("New subfolder…", self.create_folder)
        menu.addAction("Rename…", self.rename_folder)
        menu.addAction("Move…", self.move_folder)
        menu.addAction("Delete empty folder", self.delete_folder)
        menu.addSeparator()
        menu.addAction("Refresh", lambda: self.refresh())
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def open_selected_folder(self):
        path = self.selected_path()
        if path is None:
            return
        self.main_window.load_directory_in_active_browser(path, save_path_to_settings=True)

    def use_for_quick_sort(self):
        path = self.selected_path()
        if path is None:
            return
        self.main_window.load_directory_in_active_browser(path, save_path_to_settings=True)
        panel = getattr(self.main_window, "quick_sort_panel", None)
        if panel is not None:
            for index in range(panel.source_combo.count()):
                if panel.source_combo.itemData(index) == "current_folder":
                    panel.source_combo.setCurrentIndex(index)
                    break
            panel.show()
            panel.raise_()

    def create_folder(self):
        if not self._changes_allowed():
            return
        parent = self.selected_path()
        if parent is None:
            return
        name, accepted = QInputDialog.getText(self, "New folder", "Folder name:")
        name = str(name or "").strip()
        if not accepted or not name:
            return
        destination = parent / name
        if Path(name).name != name or destination.exists():
            self._warning("Cannot create folder", "Choose a single unused folder name.")
            return
        try:
            destination.mkdir()
        except OSError as exc:
            self._warning("Cannot create folder", str(exc))
            return
        self.history.record(FolderHistoryEntry("Create folder", parent, destination, time.time_ns()))
        self.refresh(select_path=destination)

    def rename_folder(self):
        if not self._changes_allowed():
            return
        source = self.selected_path()
        if not self._editable_source(source):
            return
        name, accepted = QInputDialog.getText(
            self, "Rename folder", "New name:", text=source.name
        )
        name = str(name or "").strip()
        if not accepted or not name or name == source.name:
            return
        if Path(name).name != name:
            self._warning("Cannot rename folder", "Enter a folder name, not a path.")
            return
        self._perform_move(source, source.with_name(name), "Rename folder")

    def move_folder(self):
        if not self._changes_allowed():
            return
        source = self.selected_path()
        if not self._editable_source(source) or self.root_path is None:
            return
        selected = QFileDialog.getExistingDirectory(
            self, "Move folder into", str(self.root_path)
        )
        if not selected:
            return
        parent = _absolute(selected)
        if not _within(parent, self.root_path) or _within(parent, source):
            self._warning(
                "Cannot move folder",
                "Choose a destination inside the hierarchy and outside the folder being moved.",
            )
            return
        self._perform_move(source, parent / source.name, "Move folder")

    def _move_folder_from_drop(self, source_text: str, parent_text: str):
        if not self._changes_allowed() or self.root_path is None:
            return
        source = _absolute(source_text)
        parent = _absolute(parent_text)
        if not self._editable_source(source):
            return
        if source.parent == parent:
            return
        if not _within(parent, self.root_path) or _within(parent, source):
            self._warning(
                "Cannot move folder",
                "Drop onto a folder inside the hierarchy and outside the folder being moved.",
            )
            return
        self._perform_move(source, parent / source.name, "Move folder")

    def delete_folder(self):
        if not self._changes_allowed():
            return
        source = self.selected_path()
        if not self._editable_source(source):
            return
        try:
            if any(source.iterdir()):
                self._warning(
                    "Folder is not empty",
                    "This first version only deletes empty folders so deletion remains safely undoable.",
                )
                return
        except OSError as exc:
            self._warning("Cannot inspect folder", str(exc))
            return
        reply = QMessageBox.question(
            self,
            "Delete empty folder",
            f'Delete "{source.name}"? You can undo this action.',
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            source.rmdir()
        except OSError as exc:
            self._warning("Cannot delete folder", str(exc))
            return
        self.history.record(FolderHistoryEntry("Delete folder", source.parent, source, time.time_ns()))
        self.refresh(select_path=source.parent)

    def _editable_source(self, source: Path | None) -> bool:
        return bool(source is not None and self.root_path is not None and source != self.root_path)

    def _changes_allowed(self) -> bool:
        controller = getattr(self.main_window, "quick_sort_controller", None)
        if controller is not None and controller.active:
            self._warning(
                "Quick Sort is active",
                "Exit Quick Sort before changing the folder hierarchy.",
            )
            return False
        return True

    def _perform_move(self, source: Path, destination: Path, action: str):
        if destination.exists():
            self._warning("Destination exists", str(destination))
            return
        if not self._relocate(source, destination):
            return
        self.history.record(FolderHistoryEntry(action, source, destination, time.time_ns()))
        self.refresh(select_path=destination)

    def _apply_history_entry(self, entry: FolderHistoryEntry, *, reverse: bool) -> bool:
        if not self._changes_allowed():
            return False
        if entry.action == "Create folder":
            if reverse:
                try:
                    entry.destination.rmdir()
                except OSError as exc:
                    self._warning("Cannot undo folder creation", str(exc))
                    return False
                self.refresh(select_path=entry.source)
                return True
            try:
                entry.destination.mkdir()
            except OSError as exc:
                self._warning("Cannot redo folder creation", str(exc))
                return False
            self.refresh(select_path=entry.destination)
            return True
        if entry.action == "Delete folder":
            if reverse:
                try:
                    entry.destination.mkdir()
                except OSError as exc:
                    self._warning("Cannot undo folder deletion", str(exc))
                    return False
                self.refresh(select_path=entry.destination)
                return True
            try:
                entry.destination.rmdir()
            except OSError as exc:
                self._warning("Cannot redo folder deletion", str(exc))
                return False
            self.refresh(select_path=entry.source)
            return True
        source, destination = (
            (entry.destination, entry.source) if reverse else (entry.source, entry.destination)
        )
        if not self._relocate(source, destination):
            return False
        self.refresh(select_path=destination)
        return True

    def _relocate(self, source: Path, destination: Path) -> bool:
        if self.root_path is None or not _within(source, self.root_path) or not _within(destination, self.root_path):
            self._warning("Cannot move folder", "Folder operations must remain inside the loaded hierarchy.")
            return False
        if not source.is_dir() or destination.exists():
            self._warning("Cannot move folder", "The source is missing or the destination already exists.")
            return False
        models = [getattr(self.main_window, "image_list_model", None)]
        secondary_browser = getattr(self.main_window, "_secondary_browser", None)
        models.append(getattr(secondary_browser, "image_list_model", None))
        for model in models:
            cancel_validation = getattr(model, "cancel_background_path_validation", None)
            if callable(cancel_validation):
                cancel_validation()
        browser_name = self.main_window._active_directory_browser_name()
        if browser_name == "secondary":
            secondary = getattr(self.main_window, "_secondary_browser", None)
            active_dock = getattr(secondary, "dock", None)
            current_value = getattr(
                getattr(secondary, "image_list_model", None),
                "_directory_path",
                None,
            )
        else:
            secondary = None
            active_dock = getattr(self.main_window, "image_list", None)
            current_value = getattr(self.main_window, "directory_path", None)
        current_directory = _absolute(current_value or self.root_path)
        mapped_current = current_directory
        if _within(current_directory, source):
            mapped_current = destination / current_directory.relative_to(source)
        selected_path = None
        try:
            current_index = active_dock.list_view.currentIndex()
            image = current_index.data(Qt.ItemDataRole.UserRole)
            image_path = getattr(image, "path", None)
            if image_path is not None:
                selected_path = _absolute(image_path)
        except Exception:
            selected_path = None
        mapped_selected = selected_path
        if selected_path is not None and _within(selected_path, source):
            mapped_selected = destination / selected_path.relative_to(source)
        try:
            source.rename(destination)
        except OSError as exc:
            self._warning("Cannot move folder", str(exc))
            return False
        database = ImageIndexDB(self.root_path)
        try:
            if not database.rename_path_prefix(source, destination, directory_path=self.root_path):
                destination.rename(source)
                self._warning("Cannot update folder index", "The folder move was rolled back safely.")
                return False
        finally:
            database.close()
        if browser_name == "primary":
            self.main_window.load_directory(
                mapped_current,
                save_path_to_settings=True,
                select_path=str(mapped_selected) if mapped_selected is not None else None,
            )
        elif secondary is not None:
            secondary.load_directory(mapped_current)
            if mapped_selected is not None:
                source_row = secondary.image_list_model.get_index_for_path(mapped_selected)
                if source_row >= 0:
                    source_index = secondary.image_list_model.index(source_row, 0)
                    proxy_index = secondary.proxy_image_list_model.mapFromSource(source_index)
                    if proxy_index.isValid():
                        secondary.dock.list_view.selectionModel().setCurrentIndex(
                            proxy_index,
                            QItemSelectionModel.SelectionFlag.ClearAndSelect,
                        )
        return True

    def _history_changed(self):
        manager = getattr(self.main_window, "menu_manager", None)
        if manager is not None:
            manager.update_undo_and_redo_actions()

    def _warning(self, title: str, text: str):
        QMessageBox.warning(self, title, text)
