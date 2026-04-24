import hashlib
import time

from widgets.image_list_shared import *  # noqa: F401,F403
from widgets.image_list_view import ImageListView
from PySide6.QtWidgets import (
    QInputDialog,
    QSizePolicy,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QTabBar,
    QToolButton,
)
from utils.settings import DEFAULT_SETTINGS, settings

RANDOM_SEED_MAX = 999_999
RANDOM_SEED_GENERATED_MIN = 100_000
RANDOM_SEED_GENERATED_SPACE = RANDOM_SEED_MAX - RANDOM_SEED_GENERATED_MIN + 1


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class ControlsToggleStrip(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Click to show or hide image list controls')
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._press_pos = None
        self._dragging = False
        self._floating_mode = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 2, 0)
        layout.setSpacing(2)
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(self.title_label)
        self.close_button = QToolButton()
        self.close_button.setAutoRaise(True)
        self.close_button.setText('x')
        self.close_button.setToolTip('Close this panel')
        layout.addWidget(self.close_button)
        self.setStyleSheet(
            """
            QFrame {
                border: none;
                border-top: 1px dotted palette(mid);
                border-bottom: 1px dotted palette(mid);
                background: palette(window);
            }
            QLabel {
                color: palette(mid);
                font-size: 8px;
            }
            QToolButton {
                border: none;
                color: palette(mid);
                padding: 0px;
                margin: 0px;
            }
            QToolButton:hover {
                color: palette(text);
            }
            QFrame:hover {
                background: palette(alternate-base);
            }
            """
        )
        self.set_strip_height(settings.value(
            'image_list_title_strip_height',
            defaultValue=DEFAULT_SETTINGS['image_list_title_strip_height'],
            type=int,
        ))
        self.set_floating_mode(False)

    def set_title(self, title: str):
        self.title_label.setText(str(title or 'Images'))

    def _dock_widget(self):
        widget = self.parentWidget()
        while widget is not None and not isinstance(widget, QDockWidget):
            widget = widget.parentWidget()
        return widget

    def set_strip_height(self, height: int):
        height = max(4, min(32, int(height or DEFAULT_SETTINGS['image_list_title_strip_height'])))
        if self._floating_mode:
            return
        self.setFixedHeight(height)
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        button_size = max(4, min(24, height - 1))
        self.close_button.setFixedSize(button_size, button_size)

    def set_floating_mode(self, floating: bool):
        self._floating_mode = bool(floating)
        if self._floating_mode:
            height = 32
            self.setFixedHeight(height)
            self.setMinimumHeight(height)
            self.setMaximumHeight(height)
            self.close_button.setFixedSize(28, 28)
            self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.setToolTip('Drag to dock or move this panel')
            self.setStyleSheet(
                """
                QFrame {
                    border: none;
                    background: palette(window);
                }
                QLabel {
                    color: palette(text);
                    font-size: 16px;
                }
                QToolButton {
                    border: none;
                    color: palette(mid);
                    padding: 0px;
                    margin: 0px;
                    font-size: 18px;
                }
                QToolButton:hover {
                    color: palette(text);
                    background: palette(alternate-base);
                }
                """
            )
            return

        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setToolTip('Click to show or hide image list controls')
        self.setStyleSheet(
            """
            QFrame {
                border: none;
                border-top: 1px dotted palette(mid);
                border-bottom: 1px dotted palette(mid);
                background: palette(window);
            }
            QLabel {
                color: palette(mid);
                font-size: 8px;
            }
            QToolButton {
                border: none;
                color: palette(mid);
                padding: 0px;
                margin: 0px;
            }
            QToolButton:hover {
                color: palette(text);
            }
            QFrame:hover {
                background: palette(alternate-base);
            }
            """
        )
        self.set_strip_height(settings.value(
            'image_list_title_strip_height',
            defaultValue=DEFAULT_SETTINGS['image_list_title_strip_height'],
            type=int,
        ))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
            self._dragging = False
            # Let QDockWidget also see the press so native dock dragging,
            # previews, and re-docking behavior stay intact.
            event.ignore()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        if (pos - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            event.ignore()
            return
        self._dragging = True
        event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._dragging:
                self.clicked.emit()
            self._press_pos = None
            self._dragging = False
            # Press/move are passed through to QDockWidget for native dragging;
            # release must pass through too so Qt does not keep a stale drag.
            event.ignore()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class MediaTypeTabBar(QTabBar):
    currentTextChanged = Signal(str)

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        self._labels: list[str] = []
        self.setDocumentMode(True)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setUsesScrollButtons(False)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.currentChanged.connect(self._on_current_changed)

        if not settings.contains(key):
            settings.setValue(key, DEFAULT_SETTINGS.get(key, 'All'))

    def addItems(self, texts: list[str]):
        for text in texts:
            label = str(text)
            self.addTab(label)
            self._labels.append(label)
        saved = str(settings.value(self.key, type=str) or '')
        if saved:
            self.setCurrentText(saved)
        elif self.count() > 0:
            self.setCurrentIndex(0)

    def currentText(self) -> str:
        index = self.currentIndex()
        if 0 <= index < len(self._labels):
            return self._labels[index]
        return ''

    def setCurrentText(self, text: str):
        try:
            index = self._labels.index(str(text))
        except ValueError:
            return
        self.setCurrentIndex(index)

    def itemText(self, index: int) -> str:
        if 0 <= index < len(self._labels):
            return self._labels[index]
        return ''

    def _on_current_changed(self, index: int):
        text = self.itemText(index)
        if text:
            settings.setValue(self.key, text)
        self.currentTextChanged.emit(text)


class SortComboBox(SettingsComboBox):
    random_seed_menu_requested = Signal(QPoint)

    def __init__(self, key: str, default: str | None = None):
        super().__init__(key=key, default=default)
        self._sort_direction = 'ASC'
        self._display_text_override = ''

    def set_sort_direction(self, sort_dir: str):
        normalized_dir = 'DESC' if str(sort_dir).upper() == 'DESC' else 'ASC'
        if self._sort_direction == normalized_dir:
            return
        self._sort_direction = normalized_dir
        self.update()

    def sort_direction(self) -> str:
        return self._sort_direction

    def set_display_text_override(self, text: str | None):
        normalized_text = str(text or '')
        if self._display_text_override == normalized_text:
            return
        self._display_text_override = normalized_text
        self.update()

    def contextMenuEvent(self, event):
        self.random_seed_menu_requested.emit(event.globalPos())
        event.accept()

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        if self._display_text_override:
            option.currentText = self._display_text_override
        option.subControls = (
            QStyle.SubControl.SC_ComboBoxFrame
            | QStyle.SubControl.SC_ComboBoxEditField
        )
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

        arrow_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxArrow,
            self,
        )
        arrow_option = QStyleOptionComboBox(option)
        arrow_option.rect = arrow_rect
        arrow_primitive = (
            QStyle.PrimitiveElement.PE_IndicatorArrowUp
            if self._sort_direction == 'DESC'
            else QStyle.PrimitiveElement.PE_IndicatorArrowDown
        )
        painter.drawPrimitive(arrow_primitive, arrow_option)


class ImageList(QDockWidget):
    deletion_marking_changed = Signal()
    directory_reload_requested = Signal()
    sort_state_changed = Signal(str, str)

    def __init__(self, proxy_image_list_model: ProxyImageListModel,
                 tag_separator: str, image_width: int):
        super().__init__()
        self.proxy_image_list_model = proxy_image_list_model
        self._default_sort_dirs = {
            'Default': 'ASC',
            'Name': 'ASC',
            'Modified': 'DESC',
            'Created': 'DESC',
            'Size': 'DESC',
            'Type': 'ASC',
            'Love / Rate / Bomb': 'ASC',
            'Random': 'ASC',
        }
        self._active_sort_by = ''
        self._sort_dir = 'ASC'
        self._skip_next_sort_activation = False
        self._max_random_seed_history = 12
        # Each `QDockWidget` needs a unique object name for saving its state.
        self.setObjectName('image_list')
        self.setWindowTitle('Images')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.filter_line_edit = FilterLineEdit()
        self.filter_line_edit.setMinimumWidth(0)
        self.filter_line_edit.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.filter_line_edit.setPlaceholderText('Filter images')

        self.controls_container = QWidget()
        self.controls_container.setMinimumWidth(0)
        self.controls_container.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.controls_layout = QHBoxLayout(self.controls_container)
        self.controls_layout.setContentsMargins(4, 2, 4, 2)
        self.controls_layout.setSpacing(6)
        sort_label = QLabel('Sort')
        sort_label.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )
        self.sort_combo_box = SortComboBox(key='image_list_sort_by')
        self.sort_combo_box.addItems(['Default', 'Name', 'Modified', 'Created',
                                       'Size', 'Type', 'Love / Rate / Bomb', 'Random'])
        self.sort_combo_box.setMinimumWidth(0)
        self.sort_combo_box.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.sort_combo_box.setMinimumContentsLength(8)

        self.media_type_combo_box = MediaTypeTabBar(key='media_type_filter')
        self.media_type_combo_box.addItems(['All', 'Images', 'Videos'])
        self.media_type_combo_box.setMinimumWidth(168)
        self.media_type_combo_box.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        self.media_type_combo_box.setStyleSheet(
            """
            QTabBar::tab {
                padding: 5px 12px;
                margin: 0 1px;
                border: 1px solid palette(mid);
                border-radius: 8px;
                background: palette(base);
                color: palette(text);
            }
            QTabBar::tab:selected {
                background: palette(alternate-base);
                color: palette(text);
                border-color: palette(dark);
                font-weight: 600;
            }
            QTabBar::tab:hover:!selected {
                background: palette(button);
                border-color: palette(dark);
            }
            """
        )

        self.controls_layout.addWidget(self.filter_line_edit, stretch=5)
        self.controls_layout.addWidget(sort_label)
        self.controls_layout.addWidget(self.sort_combo_box, stretch=2)
        self.controls_layout.addWidget(self.media_type_combo_box)

        self.controls_toggle_strip = ControlsToggleStrip()
        self.controls_toggle_strip.set_title(self.windowTitle())
        self.windowTitleChanged.connect(self.controls_toggle_strip.set_title)
        self.setTitleBarWidget(self.controls_toggle_strip)
        self.controls_toggle_strip.close_button.clicked.connect(self.close)
        self.controls_toggle_strip.clicked.connect(
            self.toggle_controls_collapsed
        )
        self.topLevelChanged.connect(self._sync_title_bar_widget_for_float_state)
        self._controls_collapsed = False

        self.list_view = ImageListView(self, proxy_image_list_model,
                                       tag_separator, image_width)
        self.list_view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )

        # Status bar with image index (left) and cache status (right) on same line
        self.image_index_label = ClickableLabel()
        self.cache_status_label = QLabel()
        self.decrease_thumbnail_size_button = QPushButton('-')
        self.thumbnail_size_label = ClickableLabel()
        self.increase_thumbnail_size_button = QPushButton('+')
        self.image_index_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.image_index_label.setToolTip("Click to jump to image index")
        self.image_index_label.clicked.connect(self._on_image_index_label_clicked)
        self.cache_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        for button, tooltip in (
            (self.decrease_thumbnail_size_button, 'Smaller thumbnails'),
            (self.increase_thumbnail_size_button, 'Larger thumbnails'),
        ):
            button.setFixedSize(22, 20)
            button.setToolTip(tooltip)

        self.thumbnail_size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_size_label.setMinimumWidth(0)
        self.thumbnail_size_label.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Preferred,
        )
        self.thumbnail_size_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thumbnail_size_label.setToolTip('Click to set thumbnail size')
        self.thumbnail_size_label.clicked.connect(
            self._on_thumbnail_size_label_clicked
        )

        self.decrease_thumbnail_size_button.clicked.connect(
            lambda: self._step_thumbnail_size(-1)
        )
        self.increase_thumbnail_size_button.clicked.connect(
            lambda: self._step_thumbnail_size(1)
        )

        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(5, 2, 5, 2)
        self.image_index_label.setMinimumWidth(84)
        self.image_index_label.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding,
            QSizePolicy.Policy.Preferred,
        )
        self.cache_status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        status_layout.addWidget(self.image_index_label, stretch=1)
        status_layout.addWidget(self.cache_status_label)
        status_layout.addSpacing(8)
        status_layout.addWidget(self.decrease_thumbnail_size_button)
        status_layout.addWidget(self.thumbnail_size_label)
        status_layout.addWidget(self.increase_thumbnail_size_button)

        # A container widget is required to use a layout with a `QDockWidget`.
        container = QWidget()
        container.setMinimumWidth(0)
        container.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        layout.setSpacing(0)  # Remove spacing between widgets
        layout.addWidget(self.controls_container)
        self.list_view.setMinimumWidth(0)
        self.list_view.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )
        layout.addWidget(self.list_view)
        layout.addLayout(status_layout)
        self.setWidget(container)
        self.restore_controls_collapsed_state()

        initial_sort = str(self.sort_combo_box.currentText() or 'Default')
        self._active_sort_by = initial_sort
        self._sort_dir = self._normalize_sort_dir(
            initial_sort,
            settings.value('image_list_sort_dir', '', type=str),
        )
        initial_random_seed = self._normalize_random_seed(
            settings.value('image_list_random_seed', 0, type=int),
        )
        source_model = self._get_source_model()
        if source_model is not None and initial_random_seed > 0:
            source_model._random_seed = initial_random_seed
        self.sort_combo_box.set_sort_direction(self._sort_dir)
        self.sort_combo_box.random_seed_menu_requested.connect(
            self._show_sort_combo_context_menu,
        )
        settings.setValue('image_list_sort_dir', self._sort_dir)
        self.sort_combo_box.currentTextChanged.connect(self._on_sort_combo_text_changed)
        self.sort_combo_box.activated.connect(self._on_sort_combo_activated)
        self._update_sort_combo_display()

        # DISABLED: Cache warming causes UI blocking
        # Connect cache warming signal to update cache status label
        # source_model = proxy_image_list_model.sourceModel()
        # if hasattr(source_model, 'cache_warm_progress'):
        #     source_model.cache_warm_progress.connect(self._update_cache_status)
        #     # Trigger initial update
        #     QTimer.singleShot(1000, lambda: self._update_cache_status(0, 0))
        self.update_thumbnail_size_controls()

    def set_title_strip_height(self, height: int):
        self.controls_toggle_strip.set_strip_height(height)

    def setObjectName(self, name: str):
        super().setObjectName(name)
        if hasattr(self, 'controls_container'):
            self.restore_controls_collapsed_state()

    def _controls_collapsed_settings_key(self) -> str:
        object_name = str(self.objectName() or 'image_list')
        return f'{object_name}_controls_collapsed'

    def restore_controls_collapsed_state(self):
        collapsed = settings.value(
            self._controls_collapsed_settings_key(),
            False,
            type=bool,
        )
        self.set_controls_collapsed(bool(collapsed), persist=False)

    def _sync_title_bar_widget_for_float_state(self, floating: bool):
        self.controls_toggle_strip.set_floating_mode(bool(floating))
        self.setTitleBarWidget(self.controls_toggle_strip)

    def add_controls_widget(self, widget: QWidget, stretch: int = 0):
        """Add a widget to the existing image-list controls row."""
        self.controls_layout.addWidget(widget, stretch)

    @Slot()
    def toggle_controls_collapsed(self):
        self.set_controls_collapsed(not self._controls_collapsed)

    def set_controls_collapsed(self, collapsed: bool, *, persist: bool = True):
        self._controls_collapsed = bool(collapsed)
        self.controls_container.setVisible(not self._controls_collapsed)
        if persist:
            settings.setValue(
                self._controls_collapsed_settings_key(),
                self._controls_collapsed,
            )
        state = 'show' if self._controls_collapsed else 'hide'
        self.controls_toggle_strip.setToolTip(
            f'Click to {state} image list controls'
        )

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    @Slot()
    def update_image_index_label(self, proxy_image_index: QModelIndex):
        image_count = self.proxy_image_list_model.rowCount()
        source_model = self.proxy_image_list_model.sourceModel()

        # In buffered pagination mode, use _total_count instead of rowCount
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            unfiltered_image_count = source_model._total_count if hasattr(source_model, '_total_count') else source_model.rowCount()
        else:
            unfiltered_image_count = source_model.rowCount()

        current_pos = proxy_image_index.row() + 1
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            try:
                src_index = self.proxy_image_list_model.mapToSource(proxy_image_index)
                if src_index.isValid() and hasattr(source_model, 'get_global_index_for_row'):
                    global_idx = source_model.get_global_index_for_row(src_index.row())
                    if global_idx >= 0:
                        current_pos = global_idx + 1
            except Exception:
                pass

        # In buffered mode, denominator should reflect total filtered dataset size, not loaded rowCount.
        denom = image_count
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            denom = unfiltered_image_count

        label_text = f'Image {current_pos} / {denom}'
        if image_count != unfiltered_image_count and denom != unfiltered_image_count:
            label_text += f' ({unfiltered_image_count} total)'
        self.image_index_label.setText(label_text)

    @Slot()
    def _on_image_index_label_clicked(self):
        """Open quick jump dialog for image index."""
        self.list_view.show_go_to_image_index_dialog()

    def _on_thumbnail_size_label_clicked(self):
        """Open direct-entry dialog for thumbnail size."""
        from PySide6.QtWidgets import QInputDialog

        list_view = getattr(self, 'list_view', None)
        if list_view is None:
            return

        current_size = int(getattr(list_view, 'current_thumbnail_size', 0) or 0)
        min_size = int(getattr(list_view, 'min_thumbnail_size', 64) or 64)
        max_size = int(getattr(list_view, 'max_thumbnail_size', 512) or 512)

        target_size, ok = QInputDialog.getInt(
            self,
            'Set Thumbnail Size',
            'Thumbnail size (px):',
            current_size,
            min_size,
            max_size,
            1,
        )
        if not ok:
            return

        main_window = self.window()
        apply_size = getattr(main_window, '_set_image_list_thumbnail_size', None)
        if callable(apply_size):
            apply_size(target_size, persist=True)
        else:
            self._adjust_thumbnail_size(target_size - current_size)

    def update_thumbnail_size_controls(self):
        """Refresh footer thumbnail-size readout and button enabled state."""
        list_view = getattr(self, 'list_view', None)
        if list_view is None:
            return

        current_size = int(getattr(list_view, 'current_thumbnail_size', 0) or 0)
        min_size = int(getattr(list_view, 'min_thumbnail_size', 64) or 64)
        max_size = int(getattr(list_view, 'max_thumbnail_size', 512) or 512)

        self.thumbnail_size_label.setText(f'{current_size}px')
        self.decrease_thumbnail_size_button.setEnabled(current_size > min_size)
        self.increase_thumbnail_size_button.setEnabled(current_size < max_size)

    def _adjust_thumbnail_size(self, delta_px: int):
        """Adjust list thumbnail size using the same stepping as Ctrl+wheel."""
        list_view = getattr(self, 'list_view', None)
        if list_view is None:
            return

        current_size = int(getattr(list_view, 'current_thumbnail_size', 0) or 0)
        target_size = current_size + int(delta_px)

        main_window = self.window()
        apply_size = getattr(main_window, '_set_image_list_thumbnail_size', None)
        if callable(apply_size):
            apply_size(target_size, persist=True)
        else:
            min_size = int(getattr(list_view, 'min_thumbnail_size', 64) or 64)
            max_size = int(getattr(list_view, 'max_thumbnail_size', 512) or 512)
            size = max(min_size, min(max_size, int(target_size)))
            list_view.current_thumbnail_size = size
            list_view.setIconSize(QSize(size, size * 3))
            list_view._update_view_mode()
            settings.setValue('image_list_thumbnail_size', size)
            self.update_thumbnail_size_controls()

    def _step_thumbnail_size(self, zoom_direction: int):
        """Advance thumbnail size by one zoom step, matching Ctrl+wheel behavior."""
        main_window = self.window()
        step_size = getattr(main_window, '_step_image_list_thumbnail_size', None)
        if callable(step_size):
            step_size(zoom_direction, persist=True)
            return
        self._adjust_thumbnail_size(20 if int(zoom_direction or 0) > 0 else -20)

    # DISABLED: Cache warming causes UI blocking
    # def _update_cache_status(self, progress: int, total: int):
    #     """Update cache status label (right side of status bar)."""
    #     source_model = self.proxy_image_list_model.sourceModel()
    #     if total == 0:
    #         # No warming active, show real cache stats
    #         if hasattr(source_model, 'get_cache_stats'):
    #             cached, total_images = source_model.get_cache_stats()
    #             if total_images > 0:
    #                 percent = int((cached / total_images) * 100)
    #                 self.cache_status_label.setText(f"💾 Cache: {cached:,} / {total_images:,} ({percent}%)")
    #             else:
    #                 self.cache_status_label.setText("")
    #         else:
    #             self.cache_status_label.setText("")
    #     else:
    #         # Warming active, show progress
    #         percent = int((progress / total) * 100) if total > 0 else 0
    #         self.cache_status_label.setText(f"🔥 Building cache: {progress:,} / {total:,} ({percent}%)")

    @Slot()
    def go_to_previous_image(self):
        selection_model = self.list_view.selectionModel()
        if selection_model is None:
            return
        current_index = selection_model.currentIndex()
        if not current_index.isValid() or current_index.row() == 0:
            return
        previous_image_index = self.proxy_image_list_model.index(
            current_index.row() - 1, 0)
        selection_model.setCurrentIndex(
            previous_image_index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )

    @Slot()
    def go_to_next_image(self):
        selection_model = self.list_view.selectionModel()
        if selection_model is None:
            return
        current_index = selection_model.currentIndex()
        if (
            not current_index.isValid()
            or current_index.row() == self.proxy_image_list_model.rowCount() - 1
        ):
            return
        next_image_index = self.proxy_image_list_model.index(
            current_index.row() + 1, 0)
        selection_model.setCurrentIndex(
            next_image_index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )

    @Slot()
    def jump_to_first_untagged_image(self):
        """
        Select the first image that has no tags, or the last image if all
        images are tagged.
        """
        proxy_image_index = None
        for proxy_image_index in range(self.proxy_image_list_model.rowCount()):
            image: Image = self.proxy_image_list_model.data(
                self.proxy_image_list_model.index(proxy_image_index, 0),
                Qt.ItemDataRole.UserRole)
            if not image.tags:
                break
        if proxy_image_index is None:
            return
        self.list_view.clearSelection()
        self.list_view.setCurrentIndex(
            self.proxy_image_list_model.index(proxy_image_index, 0))

    def get_selected_image_indices(self) -> list[QModelIndex]:
        return self.list_view.get_selected_image_indices()

    def _normalize_sort_dir(self, sort_by: str, sort_dir: str | None = None) -> str:
        normalized_sort = str(sort_by or 'Default')
        normalized_dir = str(sort_dir or '').upper()
        if normalized_dir in {'ASC', 'DESC'}:
            return normalized_dir
        if normalized_sort == self._active_sort_by and self._sort_dir in {'ASC', 'DESC'}:
            return self._sort_dir
        return self._default_sort_dirs.get(normalized_sort, 'ASC')

    def current_sort_direction(self) -> str:
        return self._sort_dir

    def _get_source_model(self):
        source_model = self.proxy_image_list_model.sourceModel()
        if source_model is None or not hasattr(source_model, 'images'):
            return None
        return source_model

    def _normalize_random_seed(self, seed_value, default: int = 0) -> int:
        try:
            normalized_seed = int(seed_value)
        except (TypeError, ValueError):
            return int(default)
        if normalized_seed <= 0:
            return int(default)
        if normalized_seed <= RANDOM_SEED_MAX:
            return normalized_seed
        return ((normalized_seed - 1) % RANDOM_SEED_MAX) + 1

    def _generate_random_seed(self) -> int:
        return RANDOM_SEED_GENERATED_MIN + (
            int(time.time_ns()) % RANDOM_SEED_GENERATED_SPACE
        )

    def _random_seed_history(self) -> list[int]:
        history = settings.value('image_list_random_seed_history', [], type=list) or []
        normalized_history: list[int] = []
        for entry in history:
            normalized_seed = self._normalize_random_seed(entry)
            if normalized_seed > 0 and normalized_seed not in normalized_history:
                normalized_history.append(normalized_seed)
        return normalized_history

    def _remember_random_seed(self, seed: int, *, remember_history: bool = True) -> int:
        normalized_seed = self._normalize_random_seed(seed)
        if normalized_seed <= 0:
            return 0

        source_model = self._get_source_model()
        if source_model is not None:
            source_model._random_seed = normalized_seed

        settings.setValue('image_list_random_seed', normalized_seed)

        if remember_history:
            history = [normalized_seed]
            history.extend(
                existing_seed
                for existing_seed in self._random_seed_history()
                if existing_seed != normalized_seed
            )
            settings.setValue(
                'image_list_random_seed_history',
                history[:self._max_random_seed_history],
            )
        self._update_sort_combo_display()
        return normalized_seed

    def _current_random_seed(self) -> int:
        source_model = self._get_source_model()
        if source_model is not None:
            source_seed = self._normalize_random_seed(
                getattr(source_model, '_random_seed', 0),
            )
            if source_seed > 0:
                return source_seed
        return self._normalize_random_seed(
            settings.value('image_list_random_seed', 0, type=int),
        )

    def current_random_seed(self) -> int:
        return self._current_random_seed()

    def _update_sort_combo_display(self):
        current_seed = self._current_random_seed()
        display_text = None
        tooltip_text = 'Sort images. Click the active sort again to reverse the order.'

        if self._active_sort_by == 'Random':
            display_text = (
                f'Random ({current_seed})'
                if current_seed > 0
                else 'Random'
            )
            tooltip_text = (
                f'Random order seed: {current_seed}. Right-click for seed actions.'
                if current_seed > 0
                else 'Random order. Right-click for seed actions.'
            )

        self.sort_combo_box.set_display_text_override(display_text)
        self.sort_combo_box.setMinimumContentsLength(
            max(8, min(len(display_text or 'Random'), 24)),
        )
        self.sort_combo_box.setToolTip(tooltip_text)

    def _apply_random_seed(self, seed: int, *, preserve_selection: bool = True) -> bool:
        normalized_seed = self._remember_random_seed(seed)
        if normalized_seed <= 0:
            return False

        target_dir = (
            self._sort_dir
            if self._active_sort_by == 'Random'
            else self._default_sort_dirs.get('Random', 'ASC')
        )
        self.set_sort_state(
            'Random',
            target_dir,
            preserve_selection=preserve_selection,
            apply_sort=True,
            emit_signal=True,
            reshuffle_random=False,
            reapply_sort=True,
        )
        return True

    def _prompt_for_random_seed(self):
        current_seed = self._current_random_seed() or self._generate_random_seed()
        seed, accepted = QInputDialog.getInt(
            self,
            'Apply Random Seed',
            'Random seed:',
            current_seed,
            1,
            RANDOM_SEED_MAX,
            1,
        )
        if accepted:
            self._apply_random_seed(seed)

    @Slot(QPoint)
    def _show_sort_combo_context_menu(self, global_pos: QPoint):
        menu = QMenu(self)

        current_seed = self._current_random_seed()
        current_seed_action = menu.addAction(
            f'Current Random Seed: {current_seed}'
            if current_seed > 0
            else 'Current Random Seed: unavailable'
        )
        if current_seed > 0:
            current_seed_action.setToolTip('Click to copy the current random seed.')
        else:
            current_seed_action.setEnabled(False)

        copy_seed_action = menu.addAction('Copy Random Seed')
        copy_seed_action.setEnabled(current_seed > 0)

        reshuffle_action = menu.addAction('New Random Order')
        apply_seed_action = menu.addAction('Apply Random Seed...')

        recent_menu = menu.addMenu('Recent Random Seeds')
        recent_seed_actions = {}
        for seed in self._random_seed_history():
            action = recent_menu.addAction(f'Random ({seed})')
            recent_seed_actions[action] = seed
        if not recent_seed_actions:
            empty_action = recent_menu.addAction('No saved seeds')
            empty_action.setEnabled(False)

        chosen_action = menu.exec(global_pos)
        if chosen_action is None:
            return

        if chosen_action is current_seed_action and current_seed > 0:
            QApplication.clipboard().setText(str(current_seed))
            return
        if chosen_action is copy_seed_action and current_seed > 0:
            QApplication.clipboard().setText(str(current_seed))
            return
        if chosen_action is reshuffle_action:
            self._apply_random_seed(self._generate_random_seed())
            return
        if chosen_action is apply_seed_action:
            self._prompt_for_random_seed()
            return

        chosen_seed = recent_seed_actions.get(chosen_action)
        if chosen_seed is not None:
            self._apply_random_seed(chosen_seed)

    def set_sort_state(
        self,
        sort_by: str,
        sort_dir: str | None = None,
        *,
        preserve_selection: bool = True,
        apply_sort: bool = True,
        emit_signal: bool = True,
        reshuffle_random: bool = False,
        reapply_sort: bool = False,
        random_seed: int | None = None,
        remember_random_seed_history: bool = False,
    ):
        normalized_sort = str(sort_by or 'Default')
        if normalized_sort not in self._default_sort_dirs:
            normalized_sort = 'Default'
        normalized_dir = self._normalize_sort_dir(normalized_sort, sort_dir)
        sort_changed = normalized_sort != self._active_sort_by
        dir_changed = normalized_dir != self._sort_dir

        if normalized_sort == 'Random' and random_seed is not None:
            self._remember_random_seed(
                random_seed,
                remember_history=remember_random_seed_history,
            )

        if self.sort_combo_box.currentText() != normalized_sort:
            previous = self.sort_combo_box.blockSignals(True)
            try:
                self.sort_combo_box.setCurrentText(normalized_sort)
            finally:
                self.sort_combo_box.blockSignals(previous)

        self._active_sort_by = normalized_sort
        self._sort_dir = normalized_dir
        self.sort_combo_box.set_sort_direction(normalized_dir)
        settings.setValue('image_list_sort_dir', normalized_dir)
        self._update_sort_combo_display()

        if apply_sort and (sort_changed or dir_changed or reshuffle_random or reapply_sort):
            self._on_sort_changed(
                normalized_sort,
                preserve_selection=preserve_selection,
                sort_dir=normalized_dir,
                reshuffle_random=reshuffle_random,
            )
        if emit_signal and (sort_changed or dir_changed):
            self.sort_state_changed.emit(normalized_sort, normalized_dir)

    @Slot(str)
    def _on_sort_combo_text_changed(self, sort_by: str):
        previous_sort = self._active_sort_by
        self._skip_next_sort_activation = str(sort_by or '') != previous_sort
        self.set_sort_state(
            sort_by,
            self._normalize_sort_dir(sort_by),
            preserve_selection=True,
            apply_sort=True,
            emit_signal=True,
            reshuffle_random=(str(sort_by or '') == 'Random' and previous_sort != 'Random'),
        )

    @Slot(int)
    def _on_sort_combo_activated(self, index: int):
        activated_sort = str(self.sort_combo_box.itemText(index) or '')
        if self._skip_next_sort_activation:
            self._skip_next_sort_activation = False
            return
        if not activated_sort or activated_sort != self._active_sort_by:
            return
        toggled_dir = 'DESC' if self._sort_dir == 'ASC' else 'ASC'
        self.set_sort_state(
            activated_sort,
            toggled_dir,
            preserve_selection=True,
            apply_sort=True,
            emit_signal=True,
            reshuffle_random=False,
        )

    @Slot(str)
    def _on_sort_changed(self, sort_by: str, preserve_selection: bool = True, sort_dir: str | None = None, reshuffle_random: bool = False):
        """Sort images when sort option changes."""
        # Get the source model
        source_model = self._get_source_model()
        if source_model is None:
            return
        sort_dir = self._normalize_sort_dir(sort_by, sort_dir)
        random_seed_used = 0

        # Cancel any ongoing background enrichment (indices will be invalid after sort)
        if hasattr(source_model, '_enrichment_cancelled'):
            source_model._enrichment_cancelled.set()
            print("[SORT] Cancelled background enrichment (reordering images)")

        # Safe file stat getter with fallback
        def safe_stat(img, attr, default=0):
            try:
                return getattr(img.path.stat(), attr)
            except (OSError, AttributeError):
                return default

        def reaction_sort_bucket(img):
            rating_value = float(getattr(img, 'rating', 0.0) or 0.0)
            has_rating = rating_value > 0.0
            has_love = bool(getattr(img, 'love', False))
            has_bomb = bool(getattr(img, 'bomb', False))
            if has_love and not has_bomb and has_rating:
                return 0
            if has_love and not has_bomb:
                return 1
            if has_love and has_bomb and has_rating:
                return 2
            if has_love and has_bomb:
                return 3
            if not has_love and not has_bomb:
                return 4
            return 5

        def reaction_sort_time_value(img):
            rating_value = float(getattr(img, 'rating', 0.0) or 0.0)
            active_curated = (
                rating_value > 0.0
                or bool(getattr(img, 'love', False))
                or bool(getattr(img, 'bomb', False))
            )
            if active_curated:
                return float(
                    getattr(img, 'reaction_updated_at', None)
                    or getattr(img, 'ctime', None)
                    or safe_stat(img, 'st_ctime')
                )
            return float(getattr(img, 'ctime', None) or safe_stat(img, 'st_ctime'))

        # Sort the images list
        try:
            selected_image = None
            if preserve_selection:
                # Get currently selected image BEFORE sorting (to scroll to it after).
                # During folder-load replay, currentIndex can be stale while models churn.
                current_index = self.list_view.currentIndex()
                if (current_index.isValid()
                        and current_index.model() is self.proxy_image_list_model):
                    source_index = self.proxy_image_list_model.mapToSource(current_index)
                    if source_index.isValid():
                        selected_image = source_model.data(
                            source_index, Qt.ItemDataRole.UserRole
                        )
                if selected_image:
                    print(f"[SORT] Will scroll to selected image: {selected_image.path.name}")
                else:
                    print(f"[SORT] No valid current index to scroll to")
            else:
                print("[SORT] Skipping selection capture during folder-load sort replay")

            # BUFFERED PAGINATION MODE: Update DB sort params and reload pages
            if hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
                # Map UI sort option to DB field
                sort_map = {
                    'Default': 'file_name',
                    'Name': 'file_name',
                    'Modified': 'mtime',
                    'Created': 'ctime',
                    'Size': 'file_size',
                    'Type': 'file_type',
                    'Love / Rate / Bomb': 'love_rate_bomb',
                    'Random': 'RANDOM()',  # Now supported in DB
                }

                db_sort_field = sort_map.get(sort_by, 'file_name')
                db_sort_dir = sort_dir
                source_model._sort_field = db_sort_field
                source_model._sort_dir = db_sort_dir
                
                # STABLE RANDOM: Generate a new seed if sorting by Random, to shuffle view
                if sort_by == 'Random' and reshuffle_random:
                    source_model._random_seed = self._generate_random_seed()
                if sort_by == 'Random':
                    random_seed_used = self._normalize_random_seed(
                        getattr(source_model, '_random_seed', 0),
                    )
                
                print(f"[SORT] Buffered mode: changed DB sort to {db_sort_field} {db_sort_dir} (Seed: {getattr(source_model, '_random_seed', 0)})")

                sort_restore_target = None
                if selected_image is not None and hasattr(source_model, 'resolve_restore_target'):
                    try:
                        sort_restore_target = source_model.resolve_restore_target(selected_image.path)
                    except Exception:
                        sort_restore_target = None
                if (
                    isinstance(sort_restore_target, dict)
                    and int(sort_restore_target.get('target_global', -1)) >= 0
                    and hasattr(self.list_view, '_arm_pending_targeted_relocation')
                ):
                    try:
                        self.list_view._arm_pending_targeted_relocation(
                            int(sort_restore_target['target_global']),
                            reason='sort_restore',
                            source_model=source_model,
                            hold_s=30.0,
                        )
                    except Exception:
                        pass

                # CRITICAL: Inform Qt that the entire model is being reset
                source_model.beginResetModel()
                
                try:
                    # Clear all pages and reload from DB with new sort
                    with source_model._page_load_lock:
                        source_model._pages.clear()
                        source_model._loading_pages.clear()
                        source_model._page_load_order.clear()
                    if hasattr(source_model, '_page_debouncer'):
                        source_model._page_debouncer.stop()
                    if hasattr(source_model, '_pending_page_range'):
                        source_model._pending_page_range = None

                    if (
                        isinstance(sort_restore_target, dict)
                        and int(sort_restore_target.get('target_global', -1)) >= 0
                        and hasattr(source_model, 'prepare_target_window')
                    ):
                        source_model.prepare_target_window(
                            int(sort_restore_target['target_global']),
                            sync_target_page=True,
                            include_buffer=False,
                            prefer_forward=True,
                            emit_update=False,
                            request_async_window=False,
                            restart_enrichment=False,
                        )
                    else:
                        # Reload first 3 pages with new sort order
                        for page_num in range(3):
                            source_model._load_page_sync(page_num)
                finally:
                    source_model.endResetModel()

                if (
                    isinstance(sort_restore_target, dict)
                    and int(sort_restore_target.get('target_global', -1)) >= 0
                ):
                    self._sort_restore_target_global = int(sort_restore_target['target_global'])
                    if hasattr(source_model, '_emit_paginated_layout_refresh'):
                        source_model._emit_paginated_layout_refresh()
                    else:
                        source_model._emit_pages_updated()
                    if hasattr(source_model, 'prepare_target_window'):
                        source_model.prepare_target_window(
                            int(sort_restore_target['target_global']),
                            sync_target_page=False,
                            include_buffer=True,
                            prefer_forward=True,
                            emit_update=False,
                            request_async_window=True,
                            restart_enrichment=False,
                        )
                    QTimer.singleShot(0, self._do_scroll_after_sort)
                else:
                    try:
                        delattr(self, '_sort_restore_target_global')
                    except Exception:
                        pass
                    # Trigger layout update - emit pages_updated FIRST so proxy invalidates
                    source_model._emit_pages_updated()
                    # source_model.layoutChanged.emit() # Redundant with endResetModel()
                    
                    # Restart background enrichment (essential for updating placeholders)
                    if hasattr(source_model, '_start_paginated_enrichment'):
                        source_model._start_paginated_enrichment(
                            window_pages={0},
                            scope='window',
                        )

            else:
                # NORMAL MODE: Sort in-memory list
                source_model.beginResetModel()
                try:
                    reverse = sort_dir == 'DESC'
                    if sort_by == 'Default':
                        # Use natural sort from image_list_model (same as initial load)
                        source_model.images.sort(
                            key=lambda img: natural_sort_key(img.path),
                            reverse=reverse,
                        )
                    elif sort_by == 'Name':
                        # Natural sort by filename only (not full path)
                        source_model.images.sort(
                            key=lambda img: natural_sort_key(Path(img.path.name)),
                            reverse=reverse,
                        )
                    elif sort_by == 'Modified':
                        source_model.images.sort(
                            key=lambda img: safe_stat(img, 'st_mtime'),
                            reverse=reverse,
                        )
                    elif sort_by == 'Created':
                        source_model.images.sort(
                            key=lambda img: safe_stat(img, 'st_ctime'),
                            reverse=reverse,
                        )
                    elif sort_by == 'Size':
                        source_model.images.sort(
                            key=lambda img: safe_stat(img, 'st_size'),
                            reverse=reverse,
                        )
                    elif sort_by == 'Type':
                        source_model.images.sort(
                            key=lambda img: (img.path.suffix.lower(), natural_sort_key(img.path.name)),
                            reverse=reverse,
                        )
                    elif sort_by == 'Love / Rate / Bomb':
                        source_model.images.sort(
                            key=lambda img: (
                                reaction_sort_bucket(img),
                                -float(img.rating or 0.0),
                                -reaction_sort_time_value(img),
                                natural_sort_key(img.path),
                            ),
                            reverse=reverse,
                        )
                    elif sort_by == 'Random':
                        if reshuffle_random or not isinstance(getattr(source_model, '_random_seed', None), int):
                            source_model._random_seed = self._generate_random_seed()
                        random_seed = int(getattr(source_model, '_random_seed', 0) or 0)
                        random_seed_used = self._normalize_random_seed(random_seed)
                        source_model.images.sort(
                            key=lambda img: hashlib.sha1(
                                f"{random_seed}:{img.path}".encode('utf-8', 'ignore')
                            ).hexdigest(),
                            reverse=reverse,
                        )

                    # Rebuild aspect ratio cache after reordering
                    if hasattr(source_model, '_rebuild_aspect_ratio_cache'):
                        source_model._rebuild_aspect_ratio_cache()
                finally:
                    source_model.endResetModel()

                # Restart background enrichment with new sorted order
                if hasattr(source_model, '_restart_enrichment'):
                    source_model._restart_enrichment()

            if sort_by == 'Random' and random_seed_used > 0:
                self._remember_random_seed(random_seed_used)
            else:
                self._update_sort_combo_display()

            # --- SELECTION RESTORATION ---
            # Use a class-level variable and a single shot timer to avoid multiple connections
            if selected_image:
                self._image_to_scroll_to = selected_image
                
                try:
                    # Disconnect previous if any
                    self.list_view.layout_ready.disconnect(self._do_scroll_after_sort)
                except Exception:
                    pass
                    
                self.list_view.layout_ready.connect(self._do_scroll_after_sort)
                
                # Fallback timer (1s)
                QTimer.singleShot(1000, self._do_scroll_after_sort)
            else:
                 self.list_view.verticalScrollBar().setValue(0)

        except Exception as e:
            import traceback
            print(f"Sort error: {e}")
            traceback.print_exc()
            self._update_sort_combo_display()

    @Slot()
    def _arm_sort_restore_anchor(self, source_model, target_global: int):
        """Keep the selected global item as the masonry restore target after sort."""
        if not (
            source_model
            and hasattr(source_model, '_paginated_mode')
            and source_model._paginated_mode
        ):
            return
        try:
            target_global = int(target_global)
        except Exception:
            return
        if target_global < 0:
            return

        try:
            page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
        except Exception:
            page_size = 1000

        import time as _t

        self.list_view._selected_global_index = int(target_global)
        self.list_view._restore_target_global_index = int(target_global)
        self.list_view._restore_target_page = max(
            0,
            int(target_global) // max(1, page_size),
        )
        self.list_view._restore_anchor_until = max(
            float(getattr(self.list_view, '_restore_anchor_until', 0.0) or 0.0),
            _t.time() + 4.0,
        )

    def _start_sort_restore_to_global(self, source_model, target_global: int) -> bool:
        """Route sort restore through the shared relocation pipeline."""
        if not (
            source_model
            and hasattr(source_model, '_paginated_mode')
            and source_model._paginated_mode
        ):
            return False
        try:
            target_global = int(target_global)
        except Exception:
            return False
        if target_global < 0:
            return False

        self._arm_sort_restore_anchor(source_model, int(target_global))
        if hasattr(self.list_view, 'start_targeted_relocation'):
            try:
                return bool(
                    self.list_view.start_targeted_relocation(
                        int(target_global),
                        reason='sort_restore',
                        source_model=source_model,
                    )
                )
            except Exception:
                return False
        return False

    @Slot()
    def _do_scroll_after_sort(self):
        """Scroll to the previously selected image after a sort operation completes."""
        target_global_override = getattr(self, '_reaction_sort_selection_global_override', None)
        has_global_override = isinstance(target_global_override, int) and target_global_override >= 0
        sort_restore_target = getattr(self, '_sort_restore_target_global', None)
        has_sort_restore_target = isinstance(sort_restore_target, int) and sort_restore_target >= 0
        if not hasattr(self, '_image_to_scroll_to') or not self._image_to_scroll_to:
            if not has_global_override and not has_sort_restore_target:
                return
        if has_global_override:
            try:
                delattr(self, '_reaction_sort_selection_global_override')
            except Exception:
                pass
            selected_image = None
        elif has_sort_restore_target:
            try:
                delattr(self, '_sort_restore_target_global')
            except Exception:
                pass
            selected_image = None
        else:
            selected_image = self._image_to_scroll_to
        if not has_global_override:
            self._image_to_scroll_to = None  # Clear to prevent multiple triggers
        else:
            self._image_to_scroll_to = None
        
        try:
            # Disconnect to prevent re-triggering from future layouts
            try:
                self.list_view.layout_ready.disconnect(self._do_scroll_after_sort)
            except Exception:
                pass
                
            source_model = self.proxy_image_list_model.sourceModel()
            new_proxy_index = QModelIndex()
            
            if has_sort_restore_target and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
                if self._start_sort_restore_to_global(source_model, int(sort_restore_target)):
                    return
                local_row = (
                    source_model.get_loaded_row_for_global_index(int(sort_restore_target))
                    if hasattr(source_model, 'get_loaded_row_for_global_index')
                    else -1
                )
                if local_row >= 0:
                    new_proxy_index = self.proxy_image_list_model.mapFromSource(
                        source_model.index(local_row, 0)
                    )
            elif has_global_override and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
                if self._start_sort_restore_to_global(source_model, int(target_global_override)):
                    return
                local_row = (
                    source_model.get_loaded_row_for_global_index(int(target_global_override))
                    if hasattr(source_model, 'get_loaded_row_for_global_index')
                    else -1
                )
                if local_row >= 0:
                    new_proxy_index = self.proxy_image_list_model.mapFromSource(
                        source_model.index(local_row, 0)
                    )
            elif selected_image is not None:
                try:
                    if hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
                        target_global = (
                            source_model.get_global_rank_for_path(selected_image.path)
                            if hasattr(source_model, 'get_global_rank_for_path')
                            else -1
                        )
                        if isinstance(target_global, int) and target_global >= 0:
                            if self._start_sort_restore_to_global(source_model, int(target_global)):
                                return
                            local_row = (
                                source_model.get_loaded_row_for_global_index(int(target_global))
                                if hasattr(source_model, 'get_loaded_row_for_global_index')
                                else -1
                            )
                            if local_row >= 0:
                                new_proxy_index = self.proxy_image_list_model.mapFromSource(
                                    source_model.index(local_row, 0)
                                )
                    else:
                        new_source_row = source_model.images.index(selected_image)
                        new_proxy_index = self.proxy_image_list_model.mapFromSource(source_model.index(new_source_row, 0))
                except (ValueError, AttributeError):
                    pass

            if new_proxy_index.isValid():
                from PySide6.QtWidgets import QAbstractItemView
                self.list_view.setCurrentIndex(new_proxy_index)
                self.list_view.scrollTo(new_proxy_index, QAbstractItemView.ScrollHint.PositionAtCenter)
            else:
                # Not loaded or filtered out
                pass
        except Exception as e:
            print(f"[SORT] Scroll restoration failed: {e}")
            pass

    @Slot()
    def toggle_deletion_marking(self):
        """Toggle the deletion marking for selected images."""
        selected_indices = self.list_view.selectedIndexes()
        print(f"[DEBUG] toggle_deletion_marking called, selected_indices: {len(selected_indices)}")
        if not selected_indices:
            return

        # Get the images and toggle their marking
        for proxy_index in selected_indices:
            source_index = self.proxy_image_list_model.mapToSource(proxy_index)
            image = self.proxy_image_list_model.sourceModel().data(
                source_index, Qt.ItemDataRole.UserRole)
            if image:
                old_value = image.marked_for_deletion
                image.marked_for_deletion = not image.marked_for_deletion
                print(f"[DEBUG] Toggled image {image.path.name}: {old_value} -> {image.marked_for_deletion}")

        # Trigger repaint
        self.list_view.viewport().update()

        # Emit signal to update delete button visibility
        print(f"[DEBUG] Emitting deletion_marking_changed signal")
        self.deletion_marking_changed.emit()

    def get_marked_for_deletion_count(self):
        """Get count of images marked for deletion."""
        source_model = self.proxy_image_list_model.sourceModel()
        count = 0
        for row in range(source_model.rowCount()):
            index = source_model.index(row, 0)
            image = source_model.data(index, Qt.ItemDataRole.UserRole)
            if image and hasattr(image, 'marked_for_deletion') and image.marked_for_deletion:
                count += 1
        return count

    @Slot()
    def unmark_all_images(self):
        """Remove deletion marking from all images."""
        source_model = self.proxy_image_list_model.sourceModel()
        for row in range(source_model.rowCount()):
            index = source_model.index(row, 0)
            image = source_model.data(index, Qt.ItemDataRole.UserRole)
            if image and hasattr(image, 'marked_for_deletion'):
                image.marked_for_deletion = False

        # Trigger repaint
        self.list_view.viewport().update()

        # Emit signal to update delete button visibility
        self.deletion_marking_changed.emit()

    @Slot()
    def delete_marked_images(self):
        """Delete all images marked for deletion."""
        source_model = self.proxy_image_list_model.sourceModel()
        marked_images = []
        marked_indices = []

        # Collect all marked images and their proxy indices
        for row in range(self.proxy_image_list_model.rowCount()):
            proxy_index = self.proxy_image_list_model.index(row, 0)
            image = self.proxy_image_list_model.data(proxy_index, Qt.ItemDataRole.UserRole)
            if image and hasattr(image, 'marked_for_deletion') and image.marked_for_deletion:
                marked_images.append(image)
                marked_indices.append(row)

        if not marked_images:
            return

        marked_count = len(marked_images)
        title = f'Delete {pluralize("Image", marked_count)}'
        question = (f'Delete {marked_count} marked '
                    f'{pluralize("image", marked_count)} and '
                    f'{"its" if marked_count == 1 else "their"} '
                    f'{pluralize("caption", marked_count)}?')
        reply = get_confirmation_dialog_reply(title, question)
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Calculate the index to focus after deletion
        if marked_indices:
            max_marked_row = marked_indices[-1]
            total_rows = self.proxy_image_list_model.rowCount()
            # Set next index: use the row after the last deleted one, or the one before if it's the last
            next_index = max_marked_row + 1 - len(marked_indices)
            if next_index >= total_rows - len(marked_indices):
                # If we're deleting at the end, focus on the image before the first deleted one
                next_index = max(0, marked_indices[0] - 1)
            # Store in main window for use after reload
            main_window = self.parent()
            main_window.post_deletion_index = next_index

        # Similar cleanup logic as delete_selected_images
        main_window = self.parent()
        video_was_cleaned = False
        if hasattr(main_window, 'image_viewer') and hasattr(main_window.image_viewer, 'video_player'):
            video_player = main_window.image_viewer.video_player
            if video_player.video_path:
                currently_loaded_path = Path(video_player.video_path)
                for image in marked_images:
                    if image.path == currently_loaded_path:
                        video_player.cleanup()
                        video_was_cleaned = True
                        break

        # Clear thumbnails
        for image in marked_images:
            if hasattr(image, 'is_video') and image.is_video and image.thumbnail:
                image.thumbnail = None

        if video_was_cleaned:
            from PySide6.QtCore import QThread
            QThread.msleep(100)
            QApplication.processEvents()

        # Delete files with retries
        import gc
        max_retries = 3
        deleted_paths = []
        for image in marked_images:
            success = False
            for attempt in range(max_retries):
                if attempt > 0:
                    QThread.msleep(150)
                    QApplication.processEvents()
                    gc.collect()

                image_file = QFile(str(image.path))
                if image_file.moveToTrash():
                    success = True
                    break
                elif attempt == max_retries - 1:
                    reply = QMessageBox.question(
                        self, 'Trash Failed',
                        f'Could not move {image.path.name} to trash.\nDelete permanently?',
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        if image_file.remove():
                            success = True

            if not success:
                QMessageBox.critical(self, 'Error', f'Failed to delete {image.path}.')
                continue

            # Delete caption file
            caption_file_path = image.path.with_suffix('.txt')
            if caption_file_path.exists():
                caption_file = QFile(caption_file_path)
                if not caption_file.moveToTrash():
                    caption_file.remove()
            deleted_paths.append(image.path)

        if not deleted_paths:
            return

        removed_count = 0
        try:
            removed_count = int(source_model.remove_generated_media_batch(deleted_paths) or 0)
        except Exception as e:
            print(f"[DELETE] Warning: failed to clean model/DB index: {e}")
            self.directory_reload_requested.emit()
            return

        if removed_count <= 0:
            self.directory_reload_requested.emit()
            return

        # Clear deletion marks from any remaining items and refresh the overlay state.
        for image in marked_images:
            try:
                image.marked_for_deletion = False
            except Exception:
                pass
        self.deletion_marking_changed.emit()
        self.list_view.viewport().update()

        if marked_indices:
            target_row = min(next_index, max(0, self.proxy_image_list_model.rowCount() - 1))
            if self.proxy_image_list_model.rowCount() > 0:
                proxy_index = self.proxy_image_list_model.index(target_row, 0)
                if proxy_index.isValid():
                    self.list_view.setCurrentIndex(proxy_index)
                    try:
                        self.list_view.scrollTo(proxy_index)
                    except Exception:
                        pass

__all__ = ["ImageList"]
