from enum import Enum
from pathlib import Path

from PySide6.QtCore import (QItemSelection, QItemSelectionModel, QRect, Qt,
                            Signal, Slot)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QIcon, QKeyEvent,
                           QMouseEvent, QPainter, QPalette, QWheelEvent)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                               QDockWidget, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QMessageBox, QPushButton, QStyle,
                               QStyleOptionComboBox, QStylePainter,
                               QVBoxLayout, QWidget)

from models.proxy_tag_counter_model import ProxyTagCounterModel
from models.tag_counter_model import TagCounterModel
from utils.big_widgets import TallPushButton
from utils.enums import AllTagsSortBy, SortOrder
from utils.settings import settings
from utils.settings_widgets import SettingsComboBox
from utils.text_edit_item_delegate import TextEditItemDelegate
from utils.utils import get_confirmation_dialog_reply, list_with_and, pluralize


def _single_line_text(text: str) -> str:
    return ' '.join(str(text).split())


class FilterLineEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setPlaceholderText('Search')
        self.setClearButtonEnabled(True)


class PrefixedSettingsComboBox(SettingsComboBox):
    def __init__(self, key: str, prefix: str = '', default: str | None = None):
        super().__init__(key=key, default=default)
        self.prefix = prefix
        self.left_icon = QIcon()
        self.arrow_icon = QIcon()

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ''
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        edit_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        )
        arrow_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxArrow,
            self,
        )
        icon_rect = edit_rect.adjusted(2, 0, 0, 0)
        icon_rect.setWidth(18)
        text_rect = edit_rect.adjusted(26, 0, -6, 0)
        if not self.left_icon.isNull():
            pixmap = self.left_icon.pixmap(16, 16)
            pix_x = icon_rect.left()
            pix_y = icon_rect.center().y() - 8
            painter.drawPixmap(pix_x, pix_y, pixmap)
        painter.setPen(option.palette.color(QPalette.ColorRole.ButtonText))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            f'{self.prefix}: {self.currentText()}',
        )
        if not self.arrow_icon.isNull():
            pixmap = self.arrow_icon.pixmap(12, 12)
            pix_x = arrow_rect.center().x() - 6
            pix_y = arrow_rect.center().y() - 6
            painter.drawPixmap(pix_x, pix_y, pixmap)


def _enum_value(item) -> str:
    return str(getattr(item, 'value', item))


def _normalize_sort_by(value) -> str:
    raw = _enum_value(value)
    prefix = 'AllTagsSortBy.'
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
    for sort_by in AllTagsSortBy:
        if raw == sort_by.name or raw == sort_by.value:
            return sort_by.value
    return raw


def _normalize_sort_order(value) -> str:
    raw = _enum_value(value)
    prefix = 'SortOrder.'
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
    for sort_order in SortOrder:
        if raw == sort_order.name or raw == sort_order.value:
            return sort_order.value
    return SortOrder.DESCENDING.value


class SortByOrderComboBox(QComboBox):
    sort_state_changed = Signal()

    def __init__(self):
        super().__init__()
        self._sort_order = settings.value(
            'all_tags_sort_order',
            defaultValue=SortOrder.DESCENDING,
            type=str,
        )
        for sort_by in AllTagsSortBy:
            self.addItem(_enum_value(sort_by))
        saved_sort = settings.value(
            'all_tags_sort_by',
            defaultValue=AllTagsSortBy.FREQUENCY,
            type=str,
        )
        self._sort_order = _normalize_sort_order(self._sort_order)
        self.setCurrentText(_normalize_sort_by(saved_sort))
        self.currentTextChanged.connect(self._persist_sort_by)
        self.left_icon = QIcon()
        self.arrow_icon = QIcon()

    @property
    def sort_order(self) -> str:
        return _normalize_sort_order(self._sort_order or SortOrder.DESCENDING)

    def set_sort_order(self, sort_order: str, *, emit_signal: bool = True):
        self._sort_order = _normalize_sort_order(sort_order)
        settings.setValue('all_tags_sort_order', self._sort_order)
        self.update()
        if emit_signal:
            self.sort_state_changed.emit()

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ''
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        edit_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        )
        arrow_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxArrow,
            self,
        )
        icon_rect = edit_rect.adjusted(2, 0, 0, 0)
        icon_rect.setWidth(18)
        text_rect = edit_rect.adjusted(26, 0, -6, 0)
        if not self.left_icon.isNull():
            pixmap = self.left_icon.pixmap(16, 16)
            pix_x = icon_rect.left()
            pix_y = icon_rect.center().y() - 8
            painter.drawPixmap(pix_x, pix_y, pixmap)
        painter.setPen(option.palette.color(QPalette.ColorRole.ButtonText))
        order_suffix = '↓' if self.sort_order == SortOrder.DESCENDING else '↑'
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            f'Sort by: {self.currentText()} {order_suffix}',
        )
        if not self.arrow_icon.isNull():
            pixmap = self.arrow_icon.pixmap(12, 12)
            pix_x = arrow_rect.center().x() - 6
            pix_y = arrow_rect.center().y() - 6
            painter.drawPixmap(pix_x, pix_y, pixmap)

    def _persist_sort_by(self, text: str):
        normalized = _normalize_sort_by(text)
        settings.setValue('all_tags_sort_by', normalized)
        self.update()
        self.sort_state_changed.emit()


class AllTagsItemDelegate(TextEditItemDelegate):
    def paint(self, painter, option, index):
        style = option.widget.style() if option.widget is not None else QApplication.style()

        tag, count = index.data(Qt.ItemDataRole.UserRole)
        tag_text = _single_line_text(tag)
        source_model = getattr(index.model(), 'tag_counter_model', None)
        filtered_counts = getattr(source_model, 'most_common_tags_filtered', None)
        if filtered_counts is None:
            count_text = str(count)
        else:
            filtered_count = filtered_counts.get(tag, 0)
            if filtered_count == count:
                count_text = str(count)
            else:
                count_text = f'{filtered_count}/{count}'

        viewport = option.widget.viewport() if option.widget is not None and hasattr(option.widget, 'viewport') else None
        scrollbar_width = 0
        if option.widget is not None and hasattr(option.widget, 'verticalScrollBar'):
            scrollbar = option.widget.verticalScrollBar()
            if scrollbar is not None and scrollbar.isVisible():
                scrollbar_width = scrollbar.width()

        text_rect = option.rect.adjusted(8, 0, -(8 + scrollbar_width + 2), 0)
        count_font = QFont(option.font)
        count_font.setWeight(QFont.Weight.Medium)
        count_metrics = QFontMetrics(count_font)
        count_width = max(28, count_metrics.horizontalAdvance(count_text) + 2)
        count_rect = QRect(
            text_rect.right() - count_width,
            text_rect.top(),
            count_width,
            text_rect.height(),
        )
        tag_rect = QRect(
            text_rect.left(),
            text_rect.top(),
            max(0, count_rect.left() - text_rect.left() - 8),
            text_rect.height(),
        )

        palette = option.palette
        background = palette.color(QPalette.ColorRole.Base)
        if option.state & QStyle.StateFlag.State_Selected:
            background = palette.color(QPalette.ColorRole.Highlight)
            tag_color = palette.color(QPalette.ColorRole.HighlightedText)
            count_color = palette.color(QPalette.ColorRole.HighlightedText)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            background = QColor('#303030')
            tag_color = palette.color(QPalette.ColorRole.Text)
            count_color = QColor('#b9b9b9')
        else:
            tag_color = palette.color(QPalette.ColorRole.Text)
            count_color = palette.color(QPalette.ColorRole.PlaceholderText)

        painter.save()
        painter.fillRect(option.rect, background)
        painter.setPen(tag_color)
        painter.setFont(option.font)
        painter.drawText(tag_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, tag_text)
        painter.setPen(count_color)
        painter.setFont(count_font)
        painter.drawText(count_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, count_text)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(24, size.height() - 4))
        return size


class ClickAction(str, Enum):
    FILTER_IMAGES = 'Filter images for tag'
    ADD_TO_SELECTED = 'Add tag to selected images'
    MANAGE_TAGS = 'Manage tags (mass select)'


class AllTagsList(QListView):
    image_list_filter_requested = Signal(str, str)
    tag_addition_requested = Signal(str)
    tags_deletion_requested = Signal(list)

    def __init__(self, proxy_tag_counter_model: ProxyTagCounterModel,
                 all_tags_editor: 'AllTagsEditor'):
        super().__init__()
        self.setModel(proxy_tag_counter_model)
        self.all_tags_editor = all_tags_editor
        self.delegate = AllTagsItemDelegate(self)
        self.setItemDelegate(self.delegate)
        # Keep the tag list on a single-line rendering path. Wrapped rows force
        # expensive size-hint recalculation for the whole list while splitter
        # drags resize the dock.
        self.setWordWrap(False)
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        # `selectionChanged` must be used and not `currentChanged` because
        # `currentChanged` is not emitted when the same tag is deselected and
        # selected again.
        self.selectionModel().selectionChanged.connect(
            self.handle_selection_change)
        self.min_zoom = 50
        self.max_zoom = 300
        self.zoom_step = 10
        self.current_zoom = settings.value(
            'all_tags_zoom',
            defaultValue=100,
            type=int,
        )
        self.current_zoom = max(self.min_zoom, min(self.max_zoom, self.current_zoom))
        self._apply_zoom(self.current_zoom)

    def mousePressEvent(self, event: QMouseEvent):
        click_action = (self.all_tags_editor.click_action_combo_box
                        .currentText())
        if click_action == ClickAction.ADD_TO_SELECTED:
            index = self.indexAt(event.pos())
            tag = index.data(Qt.ItemDataRole.EditRole)
            self.tag_addition_requested.emit(tag)
        super().mousePressEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() == Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                new_zoom = min(self.current_zoom + self.zoom_step, self.max_zoom)
            else:
                new_zoom = max(self.current_zoom - self.zoom_step, self.min_zoom)
            if new_zoom != self.current_zoom:
                self.current_zoom = new_zoom
                self._apply_zoom(self.current_zoom)
                settings.setValue('all_tags_zoom', self.current_zoom)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        """
        Delete all instances of the selected tag when the delete key or
        backspace key is pressed. Also handle Ctrl+A for Select All.
        """
        if event.key() == Qt.Key.Key_A and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._do_select_all_with_filter_clear()
            event.accept()
            return
        if event.key() not in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            super().keyPressEvent(event)
            return
        self._delete_selected_tags()

    def _do_select_all_with_filter_clear(self):
        self._suppress_selection_clear_on_next_empty_filter = True
        self._ignore_handle_selection = True
        try:
            main_window = self.window()
            if hasattr(main_window, 'image_list'):
                main_window.image_list.filter_line_edit.setText('')
                if hasattr(main_window, 'apply_image_list_filter_now'):
                    main_window.apply_image_list_filter_now()
            
            # By the time we reach here, the filter has applied and the tag
            # counter model has rebuilt its rows. We can now select them all safely.
            self.selectAll()
        except Exception as e:
            print(f"Error in select all: {e}")
        finally:
            self._ignore_handle_selection = False

    def _delete_selected_tags(self):
        selected_indices = self.selectedIndexes()
        if not selected_indices:
            return
        tags = []
        tags_count = 0
        for selected_index in selected_indices:
            tag, tag_count = selected_index.data(Qt.ItemDataRole.UserRole)
            tags.append(tag)
            tags_count += tag_count
        question = (f'Delete {tags_count} {pluralize("instance", tags_count)} '
                    f'of ')
        if len(tags) < 10:
            quoted_tags = [f'"{tag}"' for tag in tags]
            question += (f'{pluralize("tag", len(tags))} '
                         f'{list_with_and(quoted_tags)}?')
        else:
            question += f'{len(tags)} tags?'
        reply = get_confirmation_dialog_reply(
            title=f'Delete {pluralize("Tag", len(tags))}', question=question)
        if reply == QMessageBox.StandardButton.Yes:
            self.tags_deletion_requested.emit(tags)

    def contextMenuEvent(self, event):
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        menu = QMenu(self)
        select_all_action = QAction('Select All', self)
        
        # When triggering selectAll from the context menu, we should apply the same
        # logic as Ctrl+A where we temporarily disable filter events and clear the filter text.
        select_all_action.triggered.connect(self._do_select_all_with_filter_clear)
        menu.addAction(select_all_action)
        
        selected_count = len(self.selectedIndexes())
        delete_selected_action = QAction(f'Delete {selected_count} Selected {pluralize("Tag", selected_count)} Globally', self)
        delete_selected_action.triggered.connect(self._delete_selected_tags)
        delete_selected_action.setEnabled(selected_count > 0)
        menu.addAction(delete_selected_action)
        
        menu.addSeparator()
        
        purge_all_action = QAction('Purge Entire Tag Database...', self)
        purge_all_wrapper = lambda: self.window().purge_all_tags() if hasattr(self.window(), 'purge_all_tags') else None
        purge_all_action.triggered.connect(purge_all_wrapper)
        menu.addAction(purge_all_action)
        
        menu.exec(event.globalPos())

    def handle_selection_change(self, selected: QItemSelection, _):
        if getattr(self, '_ignore_handle_selection', False):
            return
            
        mouse_buttons = QApplication.mouseButtons()
        if mouse_buttons & Qt.MouseButton.RightButton:
            return
            
        click_action = (self.all_tags_editor.click_action_combo_box
                        .currentText())
        if click_action != ClickAction.FILTER_IMAGES:
            return
        if not selected.indexes():
            return
        current_index = self.currentIndex()
        if not current_index.isValid():
            current_index = selected.indexes()[0]
        selected_tag = current_index.data(Qt.ItemDataRole.EditRole)
        modifiers = QApplication.keyboardModifiers()
        composition_mode = 'replace'
        if modifiers & Qt.KeyboardModifier.AltModifier:
            composition_mode = 'or'
        elif modifiers & (Qt.KeyboardModifier.ControlModifier
                          | Qt.KeyboardModifier.MetaModifier):
            composition_mode = 'and'
        self.image_list_filter_requested.emit(selected_tag, composition_mode)

    def _apply_zoom(self, zoom_percent: int):
        base_font_size = 10
        scaled_font_size = int(base_font_size * zoom_percent / 100)
        font = QFont(self.font())
        font.setPointSize(max(8, min(32, scaled_font_size)))
        self.setFont(font)
        self.delegate.set_zoom_multiplier(zoom_percent)
        self.doItemsLayout()
        self.viewport().update()


class AllTagsEditor(QDockWidget):
    def __init__(self, tag_counter_model: TagCounterModel):
        super().__init__()
        self.tag_counter_model = tag_counter_model

        # Each `QDockWidget` needs a unique object name for saving its state.
        self.setObjectName('all_tags_editor')
        self.setWindowTitle('All Tags')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)
        self.proxy_tag_counter_model = ProxyTagCounterModel(
            self.tag_counter_model)
        self._active_sort_by = ''
        self._skip_next_sort_activation = False
        self.proxy_tag_counter_model.setFilterRole(Qt.ItemDataRole.EditRole)
        self.filter_line_edit = FilterLineEdit()
        self.filter_line_edit.setObjectName('allTagsSearchInput')
        click_action_layout = QHBoxLayout()
        click_action_layout.setContentsMargins(0, 0, 0, 0)
        click_action_layout.setSpacing(8)
        self.click_action_combo_box = PrefixedSettingsComboBox(
            key='all_tags_click_action',
            prefix='Action',
        )
        self.click_action_combo_box.setObjectName('allTagsControlButton')
        self.click_action_combo_box.addItems([_enum_value(action) for action in ClickAction])
        click_action_layout.addWidget(self.click_action_combo_box, stretch=1)
        self.sort_by_combo_box = SortByOrderComboBox()
        self.sort_by_combo_box.setObjectName('allTagsControlButton')
        self.sort_by_combo_box.sort_state_changed.connect(self.sort_tags)
        self.sort_by_combo_box.currentTextChanged.connect(self._on_sort_combo_text_changed)
        self.sort_by_combo_box.activated.connect(self._on_sort_combo_activated)
        click_action_layout.addWidget(self.sort_by_combo_box, stretch=1)
        self.clear_filter_button = QPushButton('Clear Image List Filter')
        self.clear_filter_button.setObjectName('allTagsContextButton')
        self.clear_filter_button.hide()
        self.all_tags_list = AllTagsList(self.proxy_tag_counter_model,
                                         all_tags_editor=self)
        self.tag_count_label = QLabel()
        # A container widget is required to use a layout with a `QDockWidget`.
        container = QWidget()
        container.setObjectName('allTagsRoot')
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(8)
        list_container = QWidget()
        list_container.setObjectName('allTagsListContainer')
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(1, 1, 1, 1)
        list_layout.setSpacing(0)
        list_layout.addWidget(self.all_tags_list)
        footer_container = QWidget()
        footer_layout = QHBoxLayout(footer_container)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)
        footer_layout.addWidget(self.tag_count_label)
        footer_layout.addStretch()
        footer_layout.addWidget(self.clear_filter_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.filter_line_edit)
        layout.addLayout(click_action_layout)
        layout.addWidget(list_container, 1)
        layout.addWidget(footer_container)
        self.setWidget(container)
        assets_dir = Path(__file__).resolve().parents[1] / 'assets' / 'all_tags'
        chevron_path = (Path(__file__).resolve().parents[1] / 'assets'
                        / 'auto_captioner' / 'chevron-down.svg').as_posix()
        action_icon_path = (assets_dir / 'action-icon.svg').as_posix()
        sort_icon_path = (assets_dir / 'sort-icon.svg').as_posix()
        self.click_action_combo_box.left_icon = QIcon(action_icon_path)
        self.click_action_combo_box.arrow_icon = QIcon(chevron_path)
        self.sort_by_combo_box.left_icon = QIcon(sort_icon_path)
        self.sort_by_combo_box.arrow_icon = QIcon(chevron_path)
        container.setStyleSheet(
            'QWidget#allTagsRoot {'
            '  color: #e0e0e0;'
            '  font-family: "Inter", "Segoe UI", Arial, sans-serif;'
            '  font-size: 12px;'
            '}'
            'QLineEdit#allTagsSearchInput {'
            '  background: #242424;'
            '  border: 1px solid #4a4a4a;'
            '  color: #e8e8e8;'
            '  border-radius: 6px;'
            '  padding: 4px 10px;'
            '  min-height: 32px;'
            '  font-size: 12px;'
            '  font-weight: 500;'
            '}'
            'QComboBox#allTagsControlButton {'
            '  background: #3a3a3a;'
            '  border: 1px solid #3c3c3c;'
            '  color: #e0e0e0;'
            '  border-radius: 6px;'
            '  padding: 4px 10px;'
            '  min-height: 32px;'
            '  font-size: 12px;'
            '  font-weight: 500;'
            '}'
            'QComboBox#allTagsControlButton:hover {'
            '  background: #4a4a4a;'
            '}'
            'QComboBox#allTagsControlButton:focus {'
            '  border-color: #9e9e9e;'
            '}'
            'QLineEdit#allTagsSearchInput:focus {'
            '  border-color: #7aa2ff;'
            '}'
            'QComboBox#allTagsControlButton::drop-down {'
            '  subcontrol-origin: padding;'
            '  subcontrol-position: top right;'
            '  width: 18px;'
            '  border: none;'
            '  background: transparent;'
            '  margin-right: 8px;'
            '}'
            'QComboBox#allTagsControlButton::down-arrow {'
            '  image: none;'
            '  width: 0px;'
            '  height: 0px;'
            '}'
            'QListView {'
            '  background: #252525;'
              '  border: none;'
            '  outline: none;'
            '}'
            'QComboBox#allTagsControlButton QAbstractItemView {'
            '  background: #242424;'
            '  border: 1px solid #4a4a4a;'
            '  selection-background-color: #3b82f6;'
            '  selection-color: #ffffff;'
            '  padding: 4px;'
            '}'
            'QListView::item:selected {'
            '  background: #3b82f6;'
            '  color: #ffffff;'
            '}'
            'QListView::item:hover {'
            '  background: #303030;'
            '}'
            'QListView::item {'
            '  border: none;'
            '  padding: 0px;'
            '  margin: 0px;'
            '}'
            'QWidget#allTagsListContainer {'
            '  background: #252525;'
            '  border: 1px solid #3c3c3c;'
            '  border-radius: 4px;'
            '}'
            'QLabel {'
            '  color: #9e9e9e;'
            '}'
            'QPushButton#allTagsContextButton {'
            '  background: #2a1f1f;'
            '  border: 1px solid #6a3c3c;'
            '  color: #e36a6a;'
            '  border-radius: 5px;'
            '  padding: 1px 10px;'
            '  min-height: 24px;'
            '  max-height: 24px;'
            '  font-weight: 500;'
            '}'
            'QPushButton#allTagsContextButton:hover {'
            '  background: #3a2525;'
            '  border-color: #8a4a4a;'
            '}'
            'QScrollBar:vertical {'
            '  width: 8px;'
            '  background: transparent;'
            '}'
            'QScrollBar::handle:vertical {'
            '  background: #4a4a4a;'
            '  border-radius: 4px;'
            '  min-height: 24px;'
            '}'
            'QScrollBar::handle:vertical:hover {'
            '  background: #5a5a5a;'
            '}'
            'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, '
            'QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {'
            '  background: transparent;'
            '  border: none;'
            '  height: 0px;'
            '}'
        )

        self.proxy_tag_counter_model.modelReset.connect(
            self.update_tag_count_label)
        self.proxy_tag_counter_model.rowsInserted.connect(
            self.update_tag_count_label)
        self.proxy_tag_counter_model.rowsRemoved.connect(
            self.update_tag_count_label)
        self.filter_line_edit.textChanged.connect(self.set_filter)
        self.filter_line_edit.textChanged.connect(self.update_tag_count_label)
        self.click_action_combo_box.currentTextChanged.connect(
            self.set_selection_mode)
        self.set_selection_mode(self.click_action_combo_box.currentText())
        self.sort_tags()

    @Slot()
    def sort_tags(self):
        self._active_sort_by = self.sort_by_combo_box.currentText()
        self.proxy_tag_counter_model.sort_by = (self.sort_by_combo_box
                                                .currentText())
        if self.sort_by_combo_box.sort_order == SortOrder.ASCENDING:
            sort_order = Qt.SortOrder.AscendingOrder
        else:
            sort_order = Qt.SortOrder.DescendingOrder
        # `invalidate()` must be called to force the proxy model to re-sort.
        self.proxy_tag_counter_model.invalidate()
        self.proxy_tag_counter_model.sort(0, sort_order)

    @Slot(str)
    def _on_sort_combo_text_changed(self, sort_by: str):
        previous_sort = self._active_sort_by
        self._skip_next_sort_activation = str(sort_by or '') != previous_sort
        self.sort_tags()

    @Slot(int)
    def _on_sort_combo_activated(self, index: int):
        activated_sort = str(self.sort_by_combo_box.itemText(index) or '')
        if self._skip_next_sort_activation:
            self._skip_next_sort_activation = False
            return
        if not activated_sort or activated_sort != self._active_sort_by:
            return
        toggled = (
            SortOrder.ASCENDING
            if self.sort_by_combo_box.sort_order == SortOrder.DESCENDING
            else SortOrder.DESCENDING
        )
        self.sort_by_combo_box.set_sort_order(toggled)

    @Slot(str)
    def set_filter(self, filter_):
        # Replace escaped wildcard characters to make them compatible with
        # the `fnmatch` module.
        filter_ = filter_.replace(r'\?', '[?]').replace(r'\*', '[*]')
        self.proxy_tag_counter_model.filter = filter_
        # `invalidate()` must be called to force the proxy model to re-filter.
        self.proxy_tag_counter_model.invalidate()

    @Slot(str)
    def update_clear_filter_button_visibility(self, filter_text: str):
        self.clear_filter_button.setVisible(bool(str(filter_text or '').strip()))

    @Slot()
    def update_tag_count_label(self):
        total_tag_count = self.tag_counter_model.rowCount()
        filtered_tag_count = self.proxy_tag_counter_model.rowCount()
        self.tag_count_label.setText(f'{filtered_tag_count} / '
                                     f'{total_tag_count} Tags')

    @Slot(str)
    def set_selection_mode(self, click_action: str):
        if click_action in (ClickAction.FILTER_IMAGES, ClickAction.MANAGE_TAGS):
            self.all_tags_list.setSelectionMode(
                QAbstractItemView.SelectionMode.ExtendedSelection)
        elif click_action == ClickAction.ADD_TO_SELECTED:
            self.all_tags_list.setSelectionMode(
                QAbstractItemView.SelectionMode.SingleSelection)
            self.all_tags_list.selectionModel().select(
                self.all_tags_list.selectionModel().currentIndex(),
                QItemSelectionModel.SelectionFlag.ClearAndSelect)
