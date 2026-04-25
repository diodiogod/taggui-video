"""Secondary image browser dock.

Completely self-contained: filter, media-type, sort, image index label,
thumbnail controls and selection→viewer loading are all wired internally.
Zero dependency on signal_manager. Connects to the main viewer via
ContextSwitchManager when an image is clicked.

Architecture:
  - Owns ImageListModel + ProxyImageListModel + TagCounterModel
  - Contains a full ImageList dock for sort/filter/masonry UI
  - All dock signals are wired HERE to the secondary's own models
  - On selection change, emits context_activated for ContextSwitchManager
"""

import types
from pathlib import Path

from PySide6.QtCore import (
    Qt, Signal, Slot, QModelIndex, QItemSelectionModel, QObject, QTimer,
)
from models.image_list_model import ImageListModel
from models.proxy_image_list_model import ProxyImageListModel
from models.tag_counter_model import TagCounterModel
from utils.settings import settings, DEFAULT_SETTINGS, get_tag_separator
from widgets.image_list import ImageList


_PREFIX = 'secondary_browser_'


class SecondaryBrowser(QObject):
    """Manages an independent image browser dock with its own model stack.

    Creates an ImageList dock, self-wires its filter/sort/thumbnail/index
    signals to the secondary models, and emits context_activated on
    selection change so ContextSwitchManager can swap the right-side panels.

    Usage::
        browser = SecondaryBrowser(parent=main_window, ...)
        main_window.addDockWidget(Qt.LeftDockWidgetArea, browser.dock)
        browser.context_activated.connect(ctx_switch_manager.switch_to_context)
        browser.load_directory(Path('/some/folder'))
    """

    # context dict keys:
    # 'name': 'secondary'
    # 'proxy_index': QModelIndex (secondary proxy)
    # 'image_list_model', 'proxy_image_list_model', 'tag_counter_model'
    # 'image_list': the dock
    context_activated = Signal(object)

    def __init__(self, image_width=None, tag_separator=None, tokenizer=None, parent=None):
        super().__init__(parent)

        tag_sep = tag_separator or get_tag_separator()
        img_width = image_width or int(settings.value(
            'image_list_image_width',
            defaultValue=DEFAULT_SETTINGS.get('image_list_image_width', 200),
            type=int,
        ))

        _tokenizer = tokenizer if tokenizer is not None else self._load_tokenizer()

        # ── Own model stack ──────────────────────────────────────────────────
        self.image_list_model = ImageListModel(img_width, tag_sep)
        self.proxy_image_list_model = ProxyImageListModel(
            self.image_list_model, _tokenizer, tag_sep
        )
        self.image_list_model.proxy_image_list_model = self.proxy_image_list_model
        self.tag_counter_model = TagCounterModel()

        # Count tags when model changes
        self.image_list_model.modelReset.connect(self._count_tags)
        self.image_list_model.enrichment_complete.connect(self._count_tags)
        self.image_list_model.dataChanged.connect(lambda *_: self._count_tags())

        # ── Inner ImageList dock ─────────────────────────────────────────────
        self.dock: ImageList = ImageList(
            self.proxy_image_list_model,
            tag_sep,
            img_width,
        )
        self.dock.setObjectName('secondary_image_list')
        self.dock.setWindowTitle('Browser 2')

        # ── Self-wire filter / media-type → secondary proxy ──────────────────
        # These replace what signal_manager does for the primary image_list
        self.dock.filter_line_edit.textChanged.connect(self._on_filter_changed)
        self.dock.filter_line_edit.apply_requested.connect(self._apply_filter_now)
        self.dock.media_type_combo_box.currentTextChanged.connect(
            lambda _: self._apply_filter()
        )

        # ── Self-wire selection → image_index_label + context_activated ──────
        self._sel = self.dock.list_view.selectionModel()
        self._sel.currentChanged.connect(self._on_selection_changed)

        # Update image_index_label when proxy row count changes (filter applied)
        self.proxy_image_list_model.modelReset.connect(
            lambda: self._update_index_label(self._sel.currentIndex())
        )

        # ── Filter debounce timer (mirrors primary) ──────────────────────────
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._apply_filter)

        # ── Thumbnail buttons → secondary list_view ──────────────────────────
        self._patch_thumbnail_buttons()

        # ── Drag and Drop → secondary list_view ──────────────────────────────
        self._patch_drag_and_drop()

        self._is_active = False
        self._folder_name = ''

    # ─────────────────────────────────────────────────────────────────────────
    # Setup helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _load_tokenizer(self):
        try:
            from run_gui import TOKENIZER_DIRECTORY_PATH as _tpath
            from utils.utils import get_resource_path as _grp
            from transformers import AutoTokenizer
            return AutoTokenizer.from_pretrained(_grp(_tpath))
        except Exception:
            return None

    def _patch_thumbnail_buttons(self):
        """Replace the dock's _step_thumbnail_size so it targets its own list_view.

        The default implementation calls main_window._step_image_list_thumbnail_size()
        which hardcodes main_window.image_list.list_view (the primary).
        """
        from PySide6.QtCore import QSize

        dock = self.dock

        def _step(zoom_direction: int):
            list_view = dock.list_view
            if list_view is None:
                return
            try:
                target_size, _ = list_view._step_thumbnail_size_request(int(zoom_direction))
            except Exception:
                current = int(getattr(list_view, 'current_thumbnail_size', 200) or 200)
                target_size = max(50, min(600, current + (20 if zoom_direction > 0 else -20)))

            try:
                size, display_size = list_view._resolve_requested_thumbnail_size(
                    target_size, zoom_direction=0)
            except Exception:
                size = display_size = target_size

            if hasattr(list_view, '_target_thumbnail_size'):
                list_view._target_thumbnail_size = int(size)
            if int(getattr(list_view, 'current_thumbnail_size', display_size)) == display_size:
                if hasattr(dock, 'update_thumbnail_size_controls'):
                    dock.update_thumbnail_size_controls()
                return

            list_view.current_thumbnail_size = int(display_size)
            list_view.setIconSize(QSize(display_size, display_size * 3))
            list_view._update_view_mode()

            if bool(getattr(list_view, 'use_masonry', False)) and hasattr(list_view, '_resize_timer'):
                list_view._last_masonry_done_time = 0
                list_view._zoom_resize_wait_for_ctrl_release = False
                list_view._zoom_resize_snap_defer_until = 0.0
                list_view._last_ctrl_wheel_zoom_direction = 0
                list_view._last_masonry_signal = 'thumbnail_size_button'
                list_view._suppress_masonry_snap_cycles = 2
                if hasattr(list_view, '_on_resize_finished'):
                    list_view._on_resize_finished()
                list_view.viewport().update()
                list_view._resize_timer.stop()
                list_view._resize_timer.start(90)
            else:
                list_view.viewport().update()

            settings.setValue('image_list_thumbnail_size', display_size)
            if hasattr(dock, 'update_thumbnail_size_controls'):
                dock.update_thumbnail_size_controls()

        dock._step_thumbnail_size = types.MethodType(
            lambda self_dock, zoom_direction: _step(zoom_direction),
            dock,
        )

    def _patch_drag_and_drop(self):
        """Allow dropping folders onto the secondary browser to load them."""
        import types
        dock = self.dock
        list_view = dock.list_view

        def _dragEnterEvent(event):
            mime = event.mimeData()
            if mime and mime.hasUrls():
                for url in mime.urls():
                    if url.isLocalFile():
                        event.acceptProposedAction()
                        return
            event.ignore()

        def _dropEvent(event):
            # Ignore internal widget drags
            if hasattr(event, 'source') and event.source() is not None:
                event.ignore()
                return
            mime = event.mimeData()
            if mime and mime.hasUrls():
                for url in mime.urls():
                    if url.isLocalFile():
                        from pathlib import Path
                        path = Path(url.toLocalFile()).expanduser().resolve()
                        if path.is_file():
                            path = path.parent
                        if path.is_dir():
                            self.load_directory(path)
                            event.acceptProposedAction()
                            return
            event.ignore()

        # Patch the dock itself
        dock.setAcceptDrops(True)
        dock.dragEnterEvent = types.MethodType(lambda s, e: _dragEnterEvent(e), dock)
        dock.dropEvent = types.MethodType(lambda s, e: _dropEvent(e), dock)

        # Patch the inner widget if it exists
        w = dock.widget()
        if w:
            w.setAcceptDrops(True)
            w.dragEnterEvent = types.MethodType(lambda s, e: _dragEnterEvent(e), w)
            w.dropEvent = types.MethodType(lambda s, e: _dropEvent(e), w)
            
        # Patch the list_view
        if list_view:
            list_view.setAcceptDrops(True)
            list_view.dragEnterEvent = types.MethodType(lambda s, e: _dragEnterEvent(e), list_view)
            list_view.dropEvent = types.MethodType(lambda s, e: _dropEvent(e), list_view)

    # ─────────────────────────────────────────────────────────────────────────
    # Filter wiring
    # ─────────────────────────────────────────────────────────────────────────

    @Slot()
    def _on_filter_changed(self):
        """Debounce keystrokes like the primary filter timer."""
        if self._filter_timer.isActive():
            self._filter_timer.stop()
        self._filter_timer.start(250)

    @Slot()
    def _apply_filter_now(self):
        """Immediate filter (e.g. on Enter key)."""
        if self._filter_timer.isActive():
            self._filter_timer.stop()
        self._apply_filter()

    @Slot()
    def _apply_filter(self):
        try:
            media_type = self.dock.media_type_combo_box.currentText()
            self.proxy_image_list_model.set_media_type_filter(media_type)
            filter_ = self.dock.filter_line_edit.parse_filter_text()
            self.proxy_image_list_model.set_filter(filter_)
            self._update_index_label(self._sel.currentIndex())
        except Exception as exc:
            print(f'[SecondaryBrowser] filter error: {exc}')

    # ─────────────────────────────────────────────────────────────────────────
    # Image index label
    # ─────────────────────────────────────────────────────────────────────────

    def _update_index_label(self, current: QModelIndex):
        try:
            total = self.proxy_image_list_model.rowCount()
            row = current.row() + 1 if current.isValid() else 0
            self.dock.image_index_label.setText(f'{row} / {total}')
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Selection → viewer + context switch
    # ─────────────────────────────────────────────────────────────────────────

    def _on_selection_changed(self, current: QModelIndex, previous: QModelIndex):
        if not current.isValid():
            return
        self._update_index_label(current)
        try:
            ctx = {
                'name': 'secondary',
                'proxy_index': current,
                'image_list_model': self.image_list_model,
                'proxy_image_list_model': self.proxy_image_list_model,
                'tag_counter_model': self.tag_counter_model,
                'image_list': self.dock,
            }
            self.context_activated.emit(ctx)
        except Exception as exc:
            print(f'[SecondaryBrowser] selection error: {exc}')

    # ─────────────────────────────────────────────────────────────────────────
    # Tag counting
    # ─────────────────────────────────────────────────────────────────────────

    @Slot()
    def _count_tags(self):
        try:
            images = list(self.image_list_model.images or [])
            self.tag_counter_model.count_tags(images)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Title indicator
    # ─────────────────────────────────────────────────────────────────────────

    def _update_title(self):
        mark = '  ●' if self._is_active else ''
        folder = f' — {self._folder_name}' if self._folder_name else ''
        self.dock.setWindowTitle(f'Browser 2{folder}{mark}')

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def load_directory(self, path: Path):
        resolved = path.resolve()
        settings.setValue(_PREFIX + 'directory_path', str(resolved))
        self.image_list_model.load_directory(resolved)
        self._folder_name = resolved.name
        self._update_title()
        self.dock.filter_line_edit.clear()
        first = self.proxy_image_list_model.index(0, 0)
        if first.isValid():
            self._sel.setCurrentIndex(
                first,
                QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )

    def set_active_context(self, active: bool):
        self._is_active = bool(active)
        self._update_title()

    def get_selected_image_indices(self) -> list[QModelIndex]:
        return self._sel.selectedIndexes()
