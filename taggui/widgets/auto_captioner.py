import sys
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, Signal, Slot, QSize, QRect
from PySide6.QtGui import QFontMetrics, QTextCursor, QPainter, QColor, QPen
from PySide6.QtWidgets import (QAbstractScrollArea, QDockWidget, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
                               QTabWidget, QSizePolicy, QVBoxLayout, QWidget)

from auto_captioning.captioning_thread import CaptioningThread
from auto_captioning.models.wd_tagger import WdTagger
from auto_captioning.models.remote import RemoteGen
from auto_captioning.models_list import MODELS, get_model_class
from dialogs.caption_multiple_images_dialog import CaptionMultipleImagesDialog
from dialogs.prompt_history_dialog import PromptHistoryDialog
from models.image_list_model import ImageListModel
from utils.big_widgets import TallPushButton
from utils.prompt_history import get_prompt_history
from utils.field_history import get_field_history
from widgets.field_history_popup import FieldHistoryPopup
from utils.enums import CaptionDevice, CaptionPosition
from utils.settings import DEFAULT_SETTINGS, settings, get_tag_separator
from utils.settings import (
    AUTO_CAPTIONER_LAYOUT_MODE_CLASSIC,
    AUTO_CAPTIONER_LAYOUT_MODE_COMPACT,
    load_auto_captioner_layout_mode,
    normalize_auto_captioner_layout_mode,
    persist_auto_captioner_layout_mode,
)
from utils.settings_widgets import (FocusedScrollSettingsComboBox,
                                    FocusedScrollSettingsDoubleSpinBox,
                                    FocusedScrollSettingsSpinBox,
                                    SettingsBigCheckBox, SettingsLineEdit,
                                    SettingsPlainTextEdit)
from utils.utils import pluralize
from widgets.image_list import ImageList

try:
    from shiboken6 import isValid as _shiboken_is_valid
except Exception:
    _shiboken_is_valid = None


def set_text_edit_height(text_edit: QPlainTextEdit, line_count: int):
    """
    Set the height of a text edit to the height of a given number of lines.
    """
    # From https://stackoverflow.com/a/46997337.
    document = text_edit.document()
    font_metrics = QFontMetrics(document.defaultFont())
    margins = text_edit.contentsMargins()
    height = int(font_metrics.lineSpacing() * line_count
                 + margins.top() + margins.bottom()
                 + document.documentMargin() * 2
                 + text_edit.frameWidth() * 2)
    text_edit.setFixedHeight(height)


class HorizontalLine(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFrameShadow(QFrame.Shadow.Raised)


class SettingsSwitchCheckBox(SettingsBigCheckBox):
    def __init__(self, key: str, default: bool | None = None):
        super().__init__(key=key, default=default)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self.setText('')
        self._is_pointer_pressed = False
        self.setStyleSheet(
            'QCheckBox { background: transparent; padding: 0px; margin: 0px; }'
            'QCheckBox::indicator { width: 0px; height: 0px; }'
        )

    def sizeHint(self):
        return QSize(42, 24)

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self._is_pointer_pressed = True
            event.accept()
            return
        self._is_pointer_pressed = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_pointer_pressed:
            self._is_pointer_pressed = False
            if (event.button() == Qt.MouseButton.LeftButton
                    and self.rect().contains(event.position().toPoint())
                    and self.isEnabled()):
                self.toggle()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        on = self.isChecked()
        track_color = QColor('#3b82f6' if on else '#374151')
        border_color = QColor('#3b82f6' if on else '#4b5563')
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(track_color)
        painter.drawRoundedRect(rect, 12, 12)

        knob_size = rect.height() - 4
        knob_x = rect.left() + 2 if not on else rect.right() - knob_size - 2
        knob = QRect(knob_x, rect.top() + 2, knob_size, knob_size)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(knob)


class InlineEditorResizeGrip(QFrame):
    def __init__(self, target: QPlainTextEdit, minimum_height: int = 72, maximum_height: int = 480):
        super().__init__(target)
        self.target = target
        self.minimum_height = minimum_height
        self.maximum_height = maximum_height
        self._drag_start_y = 0
        self._start_height = 0
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setFixedSize(14, 14)
        self.target.installEventFilter(self)
        self.raise_()
        self._reposition()

    def eventFilter(self, watched, event):
        if watched is self.target:
            self._reposition()
        return super().eventFilter(watched, event)

    def _reposition(self):
        self.move(
            self.target.width() - self.width() - 2,
            self.target.height() - self.height() - 2,
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_y = event.globalPosition().toPoint().y()
            self._start_height = self.target.height()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint().y() - self._drag_start_y
            new_height = max(
                self.minimum_height,
                min(self.maximum_height, self._start_height + delta),
            )
            self.target.setFixedHeight(new_height)
            self._reposition()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor('#7c8696'), 1)
        painter.setPen(pen)
        w = self.width()
        h = self.height()
        painter.drawLine(w - 10, h - 3, w - 3, h - 10)
        painter.drawLine(w - 7, h - 3, w - 3, h - 7)
        painter.drawLine(w - 13, h - 3, w - 3, h - 13)


class CaptionSettingsForm:
    GENERATION_DEFAULTS = {
        'min_new_tokens': 1,
        'max_new_tokens': 100,
        'num_beams': 1,
        'length_penalty': 1.0,
        'do_sample': False,
        'temperature': 1.0,
        'top_k': 50,
        'top_p': 1.0,
        'repetition_penalty': 1.0,
        'no_repeat_ngram_size': 3,
    }
    QWEN_GENERATION_DEFAULTS = {
        **GENERATION_DEFAULTS,
        'max_new_tokens': 4096,
    }

    def __init__(self, *, use_compact_style: bool = False):
        try:
            import bitsandbytes  # noqa: F401
            self.is_bitsandbytes_available = True
        except RuntimeError:
            self.is_bitsandbytes_available = False
        except Exception:
            self.is_bitsandbytes_available = False

        self.use_compact_style = use_compact_style
        self.layout_mode = load_auto_captioner_layout_mode()
        self._page_cache = {}
        self.basic_settings_form = None
        self.advanced_settings_form_container = None
        self.wd_tagger_settings_form_container = None
        self.tabs_widget = None
        self.general_tab = None
        self.prompting_tab = None
        self.advanced_tab = None
        self.wd_tagger_tab = None

        self.model_combo_box = FocusedScrollSettingsComboBox(key='model_id')
        self.model_combo_box.setEditable(True)
        self.model_combo_box.addItems(self.get_local_model_paths())
        self.model_combo_box.addItems(MODELS)

        field_history = get_field_history()
        history_endpoints = field_history.get_values('remote_address')
        endpoints = [
            'http://localhost:1234/v1/chat/completions',
            'http://localhost:11434/v1/chat/completions',
            'http://localhost:5000/v1/chat/completions',
            'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
            'https://api.openai.com/v1/chat/completions',
            'https://api.groq.com/openai/v1/chat/completions',
        ]
        for h in reversed(history_endpoints):
            if h not in endpoints:
                endpoints.insert(0, h)

        self.remote_address_line_edit = FocusedScrollSettingsComboBox(key='remote_address')
        self.remote_address_line_edit.setEditable(True)
        self.remote_address_line_edit.addItems(endpoints)
        self.api_key_line_edit = SettingsLineEdit(key='api_key', default='')
        self.api_key_line_edit.setEchoMode(self.api_key_line_edit.EchoMode.Password)
        self.api_model_line_edit = SettingsLineEdit(
            key='api_model',
            default='gemini-3-flash-preview',
        )
        self.api_max_tokens_spin_box = FocusedScrollSettingsSpinBox(
            key='api_max_tokens', default=8192, minimum=100, maximum=200000)
        self.video_fps_spin_box = FocusedScrollSettingsDoubleSpinBox(
            key='video_fps', default=1.0, minimum=0.1, maximum=8.0)
        self.video_fps_spin_box.setSingleStep(0.5)
        self.video_fps_spin_box.setToolTip(
            'How many frames per second to sample from the video.\n'
            'Higher values capture more motion detail but increase\n'
            'request size and API cost. 1.0 fps is a good default.\n'
            'Only applies to video files.')
        self.video_max_frames_spin_box = FocusedScrollSettingsSpinBox(
            key='video_max_frames', default=16, minimum=1, maximum=64)
        self.video_max_frames_spin_box.setToolTip(
            'Maximum number of frames sent to the API for video files.\n'
            'Acts as a cap regardless of fps and video length.\n'
            'Set to 1 to caption only a single frame (fastest, no temporal analysis).\n'
            'Higher values give richer descriptions but cost more tokens.')
        self.disable_thinking_label_text = 'Disable reasoning (faster)'
        self.disable_thinking_tooltip = (
            'When checked, Qwen3.5 skips its internal reasoning chain (<think> block).\n'
            'This makes captioning 2-5x faster with minimal quality loss for\n'
            'straightforward descriptions. Disable this for complex video analysis\n'
            'where reasoning improves accuracy.'
        )
        self.disable_thinking_container, self.disable_thinking_check_box = (
            self._make_disable_thinking_container(
                use_switch=self.use_compact_style,
                checked=settings.value(
                    'disable_thinking',
                    defaultValue=DEFAULT_SETTINGS.get('disable_thinking', True),
                    type=bool,
                ),
            )
        )

        self.system_prompt_label = QLabel('System Prompt')
        self.system_prompt_text_edit = SettingsPlainTextEdit(
            key='system_prompt',
            default='You are a media captioning assistant. Your reasoning is private and will not be shown to the user. Your response must contain the complete, detailed caption — do not summarize or abbreviate what you described in your reasoning. Write the full description in your response.'
        )
        set_text_edit_height(self.system_prompt_text_edit, 3)
        self.system_prompt_history_button = QPushButton('📜')
        self.system_prompt_history_button.setToolTip('View System Prompt History')
        self.system_prompt_history_button.setMaximumWidth(30)
        self.system_prompt_history_button.setMaximumHeight(40)
        self.system_prompt_container = self._make_line_edit_row(
            self.system_prompt_text_edit,
            self.system_prompt_history_button,
        )

        self.prompt_label = QLabel('Prompt')
        self.prompt_text_edit = SettingsPlainTextEdit(key='prompt')
        set_text_edit_height(self.prompt_text_edit, 4)
        self.prompt_history_button = QPushButton('📜')
        self.prompt_history_button.setToolTip('View Prompt History')
        self.prompt_history_button.setMaximumWidth(30)
        self.prompt_history_button.setMaximumHeight(60)
        self.prompt_container = self._make_line_edit_row(
            self.prompt_text_edit,
            self.prompt_history_button,
        )

        self.caption_start_label = QLabel('Start caption with')
        self.caption_start_line_edit = SettingsLineEdit(key='caption_start')
        self.caption_start_line_edit.setClearButtonEnabled(True)
        self.caption_start_history_button = QPushButton('📜')
        self.caption_start_history_button.setToolTip('View History')
        self.caption_start_history_button.setMaximumWidth(30)
        self.caption_start_container = self._make_line_edit_row(
            self.caption_start_line_edit,
            self.caption_start_history_button,
        )

        self.caption_position_combo_box = FocusedScrollSettingsComboBox(
            key='caption_position')
        self.caption_position_combo_box.addItems(list(CaptionPosition))

        self.skip_hash_check_box = self._make_boolean_checkbox(
            'skip_hash', True, self.use_compact_style)
        self.skip_hash_container = self._make_toggle_row(
            'Skip hash tags when inserting in prompt',
            self.skip_hash_check_box,
            compact=self.use_compact_style,
        )

        self.device_label = QLabel('Device')
        self.device_combo_box = FocusedScrollSettingsComboBox(key='device')
        self.device_combo_box.addItems(list(CaptionDevice))

        self.load_in_4_bit_check_box = self._make_boolean_checkbox(
            'load_in_4_bit', True, self.use_compact_style)
        self.load_in_4_bit_container = self._make_toggle_row(
            'Load in 4-bit',
            self.load_in_4_bit_check_box,
            compact=self.use_compact_style,
        )

        self.limit_to_crop_check_box = self._make_boolean_checkbox(
            'limit_to_crop', True, self.use_compact_style)
        self.limit_to_crop_container = self._make_toggle_row(
            'Limit to crop',
            self.limit_to_crop_check_box,
            compact=self.use_compact_style,
        )

        self.remove_tag_separators_check_box = self._make_boolean_checkbox(
            'remove_tag_separators', True, self.use_compact_style)
        self.remove_tag_separators_container = self._make_toggle_row(
            'Remove tag separators in caption',
            self.remove_tag_separators_check_box,
            compact=self.use_compact_style,
        )

        self.remove_new_lines_check_box = self._make_boolean_checkbox(
            'remove_new_lines', False, self.use_compact_style)
        self.remove_new_lines_container = self._make_toggle_row(
            'Remove new lines in caption',
            self.remove_new_lines_check_box,
            compact=self.use_compact_style,
        )

        self.show_probabilities_check_box = self._make_boolean_checkbox(
            'wd_tagger_show_probabilities', True, self.use_compact_style)
        self.use_sampling_check_box = self._make_boolean_checkbox(
            'do_sample', False, self.use_compact_style)
        self.use_sampling_container = self._make_toggle_row(
            'Use sampling',
            self.use_sampling_check_box,
            compact=self.use_compact_style,
        )

        self.bad_words_line_edit = SettingsLineEdit(key='bad_words')
        self.bad_words_line_edit.setClearButtonEnabled(True)
        self.bad_words_history_button = QPushButton('📜')
        self.bad_words_history_button.setToolTip('View History')
        self.bad_words_history_button.setMaximumWidth(30)
        self.bad_words_container = self._make_line_edit_row(
            self.bad_words_line_edit,
            self.bad_words_history_button,
        )

        self.forced_words_line_edit = SettingsLineEdit(key='forced_words')
        self.forced_words_line_edit.setClearButtonEnabled(True)
        self.forced_words_history_button = QPushButton('📜')
        self.forced_words_history_button.setToolTip('View History')
        self.forced_words_history_button.setMaximumWidth(30)
        self.forced_words_container = self._make_line_edit_row(
            self.forced_words_line_edit,
            self.forced_words_history_button,
        )

        self.min_probability_spin_box = FocusedScrollSettingsDoubleSpinBox(
            key='wd_tagger_min_probability', default=0.4, minimum=0.01, maximum=1)
        self.min_probability_spin_box.setSingleStep(0.01)
        self.max_tags_spin_box = FocusedScrollSettingsSpinBox(
            key='wd_tagger_max_tags', default=30, minimum=1, maximum=999)
        self.tags_to_exclude_text_edit = SettingsPlainTextEdit(
            key='wd_tagger_tags_to_exclude')
        set_text_edit_height(self.tags_to_exclude_text_edit, 4)

        self.min_new_token_count_spin_box = FocusedScrollSettingsSpinBox(
            key='min_new_tokens', default=1, minimum=1, maximum=8192)
        self.max_new_token_count_spin_box = FocusedScrollSettingsSpinBox(
            key='max_new_tokens', default=100, minimum=1, maximum=8192)
        self.beam_count_spin_box = FocusedScrollSettingsSpinBox(
            key='num_beams', default=1, minimum=1, maximum=99)
        self.length_penalty_spin_box = FocusedScrollSettingsDoubleSpinBox(
            key='length_penalty', default=1, minimum=-5, maximum=5)
        self.length_penalty_spin_box.setSingleStep(0.1)
        self.temperature_spin_box = FocusedScrollSettingsDoubleSpinBox(
            key='temperature', default=1, minimum=0.01, maximum=2)
        self.temperature_spin_box.setSingleStep(0.01)
        self.top_k_spin_box = FocusedScrollSettingsSpinBox(
            key='top_k', default=50, minimum=0, maximum=200)
        self.top_p_spin_box = FocusedScrollSettingsDoubleSpinBox(
            key='top_p', default=1, minimum=0, maximum=1)
        self.top_p_spin_box.setSingleStep(0.01)
        self.repetition_penalty_spin_box = FocusedScrollSettingsDoubleSpinBox(
            key='repetition_penalty', default=1, minimum=1, maximum=2)
        self.repetition_penalty_spin_box.setSingleStep(0.01)
        self.no_repeat_ngram_size_spin_box = FocusedScrollSettingsSpinBox(
            key='no_repeat_ngram_size', default=3, minimum=0, maximum=5)
        self.gpu_index_spin_box = FocusedScrollSettingsSpinBox(
            key='gpu_index', default=0, minimum=0, maximum=9)
        self._configure_compact_responsive_fields()

        self.toggle_advanced_settings_form_button = TallPushButton(
            'Show Advanced Settings')
        self.reset_advanced_defaults_button = QPushButton(
            'Reset Advanced Defaults')
        self.reset_advanced_defaults_button.setObjectName(
            'autoCaptionerSecondaryButton')
        self.reset_advanced_defaults_button.clicked.connect(
            self.reset_generation_defaults)
        self.horizontal_line = HorizontalLine()

        self._advanced_settings_container = QWidget()
        self.advanced_settings_form_container = self._advanced_settings_container
        advanced_settings_form = QFormLayout(self.advanced_settings_form_container)
        advanced_settings_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        advanced_settings_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        bad_forced_words_form = QFormLayout()
        bad_forced_words_form.setRowWrapPolicy(
            QFormLayout.RowWrapPolicy.WrapAllRows)
        bad_forced_words_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        bad_forced_words_form.addRow('Discourage from caption', self.bad_words_container)
        bad_forced_words_form.addRow('Include in caption', self.forced_words_container)
        self._bad_forced_words_form = bad_forced_words_form
        advanced_settings_form.addRow(bad_forced_words_form)
        advanced_settings_form.addRow(HorizontalLine())
        advanced_settings_form.addRow('Minimum tokens', self.min_new_token_count_spin_box)
        advanced_settings_form.addRow('Maximum tokens', self.max_new_token_count_spin_box)
        advanced_settings_form.addRow('Number of beams', self.beam_count_spin_box)
        advanced_settings_form.addRow('Length penalty', self.length_penalty_spin_box)
        advanced_settings_form.addRow('Use sampling', self.use_sampling_check_box)
        advanced_settings_form.addRow('Temperature', self.temperature_spin_box)
        advanced_settings_form.addRow('Top-k', self.top_k_spin_box)
        advanced_settings_form.addRow('Top-p', self.top_p_spin_box)
        advanced_settings_form.addRow('Repetition penalty', self.repetition_penalty_spin_box)
        advanced_settings_form.addRow('No repeat n-gram size', self.no_repeat_ngram_size_spin_box)
        advanced_settings_form.addRow(self.reset_advanced_defaults_button)
        advanced_settings_form.addRow(HorizontalLine())
        advanced_settings_form.addRow('GPU index', self.gpu_index_spin_box)
        self.advanced_settings_form_container.hide()

        self._wd_tagger_settings_container = QWidget()
        self.wd_tagger_settings_form_container = self._wd_tagger_settings_container
        wd_tagger_settings_form = QFormLayout(self.wd_tagger_settings_form_container)
        wd_tagger_settings_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        wd_tagger_settings_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.tags_to_exclude_form = QFormLayout()
        self.tags_to_exclude_form.setRowWrapPolicy(
            QFormLayout.RowWrapPolicy.WrapAllRows)
        self.tags_to_exclude_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.tags_to_exclude_form.addRow('Tags to exclude', self.tags_to_exclude_text_edit)
        wd_tagger_settings_form.addRow('Show probabilities', self.show_probabilities_check_box)
        wd_tagger_settings_form.addRow('Minimum probability', self.min_probability_spin_box)
        wd_tagger_settings_form.addRow('Maximum tags', self.max_tags_spin_box)
        wd_tagger_settings_form.addRow(self.tags_to_exclude_form)
        self.wd_tagger_settings_form_container.hide()

        self.model_combo_box.currentTextChanged.connect(self.show_settings_for_model)
        self.device_combo_box.currentTextChanged.connect(self.set_load_in_4_bit_visibility)
        self.toggle_advanced_settings_form_button.clicked.connect(self.toggle_advanced_settings_form)
        self.min_new_token_count_spin_box.valueChanged.connect(self.max_new_token_count_spin_box.setMinimum)
        self.max_new_token_count_spin_box.valueChanged.connect(self.min_new_token_count_spin_box.setMaximum)

        if not self.is_bitsandbytes_available:
            self.load_in_4_bit_check_box.setChecked(False)

    def _make_form(self, *, wrap_all_rows: bool = True, label_right: bool = False) -> QFormLayout:
        form = QFormLayout()
        if wrap_all_rows:
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        if label_right:
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        return form

    def _make_line_edit_row(self, field_widget: QWidget, button: QWidget) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        field_widget.setMinimumWidth(0)
        field_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(field_widget, 1)
        layout.addWidget(button, 0)
        return container

    def _make_boolean_checkbox(self, key: str, default: bool, use_switch: bool) -> SettingsBigCheckBox:
        checkbox_cls = SettingsSwitchCheckBox if use_switch else SettingsBigCheckBox
        return checkbox_cls(key=key, default=default)

    def _make_toggle_row(
        self,
        label_text: str,
        checkbox: SettingsBigCheckBox,
        *,
        compact: bool = False,
    ) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8 if compact else 4)
        label = QLabel(label_text)
        if compact:
            layout.addWidget(checkbox)
            layout.addWidget(label)
            layout.addStretch(1)
        else:
            layout.addWidget(label)
            layout.addWidget(checkbox)
        return container

    def _make_field_block(self, label_text: str, widget: QWidget) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QLabel(label_text)
        label.setProperty('autoCaptionerFieldLabel', True)
        layout.addWidget(label)
        layout.addWidget(widget)
        return container

    def _make_dual_field_row(
        self,
        left_label: str,
        left_widget: QWidget,
        right_label: str,
        right_widget: QWidget,
    ) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._make_field_block(left_label, left_widget), 1)
        layout.addWidget(self._make_field_block(right_label, right_widget), 1)
        return container

    def _configure_compact_responsive_fields(self):
        responsive_widgets = [
            self.model_combo_box,
            self.remote_address_line_edit,
            self.api_key_line_edit,
            self.api_model_line_edit,
            self.api_max_tokens_spin_box,
            self.video_fps_spin_box,
            self.video_max_frames_spin_box,
            self.device_combo_box,
            self.gpu_index_spin_box,
            self.caption_position_combo_box,
        ]
        for widget in responsive_widgets:
            widget.setMinimumWidth(0)
            widget.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )

    def _make_disable_thinking_container(self, *, use_switch: bool, checked: bool) -> tuple[QWidget, QWidget]:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        checkbox_cls = SettingsSwitchCheckBox if use_switch else SettingsBigCheckBox
        checkbox = checkbox_cls(key='disable_thinking', default=True)
        checkbox.setToolTip(self.disable_thinking_tooltip)
        checkbox.setChecked(checked)
        if use_switch:
            layout.addWidget(checkbox)
            layout.addWidget(QLabel(self.disable_thinking_label_text))
            layout.addStretch(1)
        else:
            layout.addWidget(QLabel(self.disable_thinking_label_text))
            layout.addWidget(checkbox)
        return container, checkbox

    def reset_generation_defaults(self):
        defaults = self._get_generation_defaults_for_current_model()
        self.min_new_token_count_spin_box.setValue(
            defaults['min_new_tokens'])
        self.max_new_token_count_spin_box.setValue(
            defaults['max_new_tokens'])
        self.beam_count_spin_box.setValue(
            defaults['num_beams'])
        self.length_penalty_spin_box.setValue(
            defaults['length_penalty'])
        self.use_sampling_check_box.setChecked(
            defaults['do_sample'])
        self.temperature_spin_box.setValue(
            defaults['temperature'])
        self.top_k_spin_box.setValue(defaults['top_k'])
        self.top_p_spin_box.setValue(defaults['top_p'])
        self.repetition_penalty_spin_box.setValue(
            defaults['repetition_penalty'])
        self.no_repeat_ngram_size_spin_box.setValue(
            defaults['no_repeat_ngram_size'])

    def _get_generation_defaults_for_current_model(self) -> dict:
        lowercase_id = self.model_combo_box.currentText().lower()
        if 'qwen2.5-vl' in lowercase_id or 'qwen3.5' in lowercase_id:
            return self.QWEN_GENERATION_DEFAULTS
        return self.GENERATION_DEFAULTS

    def _apply_model_suggested_generation_defaults(self, model_id: str):
        lowercase_id = str(model_id or '').lower()
        if 'qwen2.5-vl' not in lowercase_id and 'qwen3.5' not in lowercase_id:
            return

        current_max_new_tokens = self.max_new_token_count_spin_box.value()
        if current_max_new_tokens == self.GENERATION_DEFAULTS['max_new_tokens']:
            self.max_new_token_count_spin_box.setValue(
                self.QWEN_GENERATION_DEFAULTS['max_new_tokens']
            )

    def _make_compact_secondary_button_row(self, button: QPushButton) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(button)
        layout.addStretch(1)
        return container

    def _make_compact_separator(self) -> QWidget:
        line = HorizontalLine()
        line.setObjectName('autoCaptionerCompactSeparator')
        return line

    def _make_compact_spacer(self, height: int = 4) -> QWidget:
        spacer = QWidget()
        spacer.setFixedHeight(height)
        return spacer

    @staticmethod
    def _toggle_checkbox_from_row(container: QWidget) -> SettingsBigCheckBox:
        for child in container.findChildren(SettingsBigCheckBox):
            return child
        raise RuntimeError('Expected toggle row to contain a checkbox')

    def _build_classic_basic_form(self) -> QFormLayout:
        container = QWidget()
        form = self._make_form(wrap_all_rows=True)
        container.setLayout(form)
        self.basic_settings_form = form
        form.addRow('Model', self.model_combo_box)
        form.addRow('OAI Compatible Endpoint', self.remote_address_line_edit)
        form.addRow('API Key', self.api_key_line_edit)
        form.addRow('API Model Name', self.api_model_line_edit)
        form.addRow('Max output tokens', self.api_max_tokens_spin_box)
        form.addRow('Video FPS', self.video_fps_spin_box)
        form.addRow('Max video frames', self.video_max_frames_spin_box)
        form.addRow(self.disable_thinking_container)
        form.addRow(self.system_prompt_label, self.system_prompt_container)
        form.addRow(self.prompt_label, self.prompt_container)
        form.addRow(self.caption_start_label, self.caption_start_container)
        form.addRow('Caption position', self.caption_position_combo_box)
        form.addRow(self.skip_hash_container)
        form.addRow(self.device_label, self.device_combo_box)
        form.addRow(self.load_in_4_bit_container)
        form.addRow(self.remove_tag_separators_container)
        form.addRow(self.remove_new_lines_container)
        form.addRow(self.limit_to_crop_container)
        return container

    def _build_compact_general_form(self) -> QFormLayout:
        container = QWidget()
        form = self._make_form(wrap_all_rows=True)
        container.setLayout(form)
        self.basic_settings_form = form
        form.addRow('Model', self.model_combo_box)
        form.addRow('OAI Compatible Endpoint', self.remote_address_line_edit)
        form.addRow('API Key', self.api_key_line_edit)
        form.addRow('API Model Name', self.api_model_line_edit)
        form.addRow('Max output tokens', self.api_max_tokens_spin_box)
        form.addRow(self._make_dual_field_row(
            'Video FPS',
            self.video_fps_spin_box,
            'Max video frames',
            self.video_max_frames_spin_box,
        ))
        form.addRow(self._make_dual_field_row(
            'Device',
            self.device_combo_box,
            'GPU index',
            self.gpu_index_spin_box,
        ))
        form.addRow(self.load_in_4_bit_container)
        form.addRow(self.disable_thinking_container)
        return container

    def _build_prompting_form(self) -> QFormLayout:
        if self.use_compact_style:
            return self._build_compact_prompting_form()

        container = QWidget()
        form = self._make_form(wrap_all_rows=True)
        container.setLayout(form)
        form.addRow(self.system_prompt_label, self.system_prompt_container)
        form.addRow(self.prompt_label, self.prompt_container)
        form.addRow(self.caption_start_label, self.caption_start_container)
        form.addRow('Caption position', self.caption_position_combo_box)
        form.addRow(self.skip_hash_container)
        form.addRow(self.remove_tag_separators_container)
        form.addRow(self.remove_new_lines_container)
        form.addRow(self.limit_to_crop_container)
        return container

    def _build_advanced_form(self) -> QFormLayout:
        if self.use_compact_style:
            return self._build_compact_advanced_form()

        container = QWidget()
        form = self._make_form(label_right=True)
        container.setLayout(form)
        form.addRow(self._bad_forced_words_form)
        form.addRow(HorizontalLine())
        form.addRow('Minimum tokens', self.min_new_token_count_spin_box)
        form.addRow('Maximum tokens', self.max_new_token_count_spin_box)
        form.addRow('Number of beams', self.beam_count_spin_box)
        form.addRow('Length penalty', self.length_penalty_spin_box)
        form.addRow('Use sampling', self.use_sampling_check_box)
        form.addRow('Temperature', self.temperature_spin_box)
        form.addRow('Top-k', self.top_k_spin_box)
        form.addRow('Top-p', self.top_p_spin_box)
        form.addRow('Repetition penalty', self.repetition_penalty_spin_box)
        form.addRow('No repeat n-gram size', self.no_repeat_ngram_size_spin_box)
        if not self.use_compact_style:
            form.addRow(HorizontalLine())
            form.addRow('GPU index', self.gpu_index_spin_box)
        return container

    def _build_compact_prompting_form(self) -> QWidget:
        self._configure_compact_resizable_text_edit(
            self.system_prompt_text_edit,
            minimum_height=72,
            maximum_height=420,
            initial_height=120,
        )
        self._configure_compact_resizable_text_edit(
            self.prompt_text_edit,
            minimum_height=96,
            maximum_height=520,
            initial_height=144,
        )

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._make_compact_text_panel(
            'System Prompt',
            self.system_prompt_text_edit,
            self.system_prompt_history_button,
        ))
        layout.addWidget(self._make_compact_text_panel(
            'Prompt',
            self.prompt_text_edit,
            self.prompt_history_button,
        ))
        layout.addWidget(self._make_field_block(
            'Start caption with',
            self.caption_start_container,
        ))
        layout.addWidget(self._make_field_block(
            'Caption position',
            self.caption_position_combo_box,
        ))
        layout.addWidget(self.skip_hash_container)
        layout.addWidget(self.remove_tag_separators_container)
        layout.addWidget(self.remove_new_lines_container)
        layout.addWidget(self.limit_to_crop_container)
        layout.addStretch(1)
        return container

    def _configure_compact_resizable_text_edit(
        self,
        text_edit: QPlainTextEdit,
        *,
        minimum_height: int,
        maximum_height: int,
        initial_height: int,
    ):
        text_edit.setMinimumWidth(0)
        text_edit.setMinimumHeight(minimum_height)
        text_edit.setMaximumHeight(maximum_height)
        text_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        text_edit.setFixedHeight(initial_height)
        existing_grip = getattr(text_edit, '_inline_resize_grip', None)
        if existing_grip is None:
            text_edit._inline_resize_grip = InlineEditorResizeGrip(
                text_edit,
                minimum_height=minimum_height,
                maximum_height=maximum_height,
            )
        else:
            existing_grip.minimum_height = minimum_height
            existing_grip.maximum_height = maximum_height
            existing_grip._reposition()

    def _build_compact_advanced_form(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._make_field_block(
            'Discourage from caption',
            self.bad_words_container,
        ))
        layout.addWidget(self._make_field_block(
            'Include in caption',
            self.forced_words_container,
        ))
        layout.addWidget(self._make_dual_field_row(
            'Minimum tokens',
            self.min_new_token_count_spin_box,
            'Maximum tokens',
            self.max_new_token_count_spin_box,
        ))
        layout.addWidget(self._make_dual_field_row(
            'Number of beams',
            self.beam_count_spin_box,
            'Length penalty',
            self.length_penalty_spin_box,
        ))
        layout.addWidget(self.use_sampling_container)
        layout.addWidget(self._make_dual_field_row(
            'Temperature',
            self.temperature_spin_box,
            'Top-k',
            self.top_k_spin_box,
        ))
        layout.addWidget(self._make_dual_field_row(
            'Top-p',
            self.top_p_spin_box,
            'Repetition penalty',
            self.repetition_penalty_spin_box,
        ))
        layout.addWidget(self._make_field_block(
            'No repeat n-gram size',
            self.no_repeat_ngram_size_spin_box,
        ))
        layout.addWidget(self._make_compact_spacer(2))
        layout.addWidget(
            self._make_compact_secondary_button_row(
                self.reset_advanced_defaults_button
            )
        )
        layout.addStretch(1)
        return container

    def _make_compact_text_panel(
        self,
        label_text: str,
        field_widget: QWidget,
        button: QWidget,
    ) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        field_widget.setMinimumWidth(0)
        field_widget.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )
        button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )

        label = QLabel(label_text)
        label.setProperty('autoCaptionerFieldLabel', True)

        editor_row = QWidget()
        editor_row_layout = QHBoxLayout(editor_row)
        editor_row_layout.setContentsMargins(0, 0, 0, 0)
        editor_row_layout.setSpacing(4)
        editor_row_layout.addWidget(field_widget, 1)
        editor_row_layout.addWidget(button, 0)

        layout.addWidget(label)
        layout.addWidget(editor_row, 1)
        return container

    def _build_wd_tagger_form(self) -> QFormLayout:
        container = QWidget()
        form = self._make_form(label_right=True)
        container.setLayout(form)
        form.addRow('Show probabilities', self.show_probabilities_check_box)
        form.addRow('Minimum probability', self.min_probability_spin_box)
        form.addRow('Maximum tags', self.max_tags_spin_box)
        form.addRow(self.tags_to_exclude_form)
        return container

    def build_page(self, layout_mode: str) -> QWidget:
        layout_mode = normalize_auto_captioner_layout_mode(layout_mode)
        cached_page = self._page_cache.get(layout_mode)
        if cached_page is not None:
            self.layout_mode = layout_mode
            return cached_page
        self.layout_mode = layout_mode

        page = QWidget()
        root_layout = QVBoxLayout(page)
        if layout_mode == AUTO_CAPTIONER_LAYOUT_MODE_COMPACT:
            root_layout.setContentsMargins(8, 8, 8, 8)
            root_layout.setSpacing(8)

        if layout_mode == AUTO_CAPTIONER_LAYOUT_MODE_CLASSIC:
            root_layout.addWidget(self._build_classic_basic_form())
            root_layout.addWidget(self.wd_tagger_settings_form_container)
            root_layout.addWidget(self.horizontal_line)
            root_layout.addWidget(self.toggle_advanced_settings_form_button)
            root_layout.addWidget(self.advanced_settings_form_container)
            root_layout.addStretch(1)
            self.advanced_settings_form_container.hide()
            self.toggle_advanced_settings_form_button.setText('Show Advanced Settings')
        else:
            root_layout.addWidget(self._build_tabs())
            root_layout.addStretch(1)
        self.show_settings_for_model(self.model_combo_box.currentText())
        self.set_load_in_4_bit_visibility(self.device_combo_box.currentText())
        self._page_cache[layout_mode] = page
        return page

    def _wrap_tab_content(self, content_widget: QWidget) -> QScrollArea:
        scroll_area = QScrollArea()
        scroll_area.setObjectName('autoCaptionerTabScrollArea')
        scroll_area.setMinimumHeight(0)
        scroll_area.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content_widget.setMinimumHeight(0)
        content_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        scroll_area.setWidget(content_widget)
        return scroll_area

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        self.tabs_widget = tabs
        tabs.setMinimumHeight(0)
        tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        tabs.setDocumentMode(True)
        tabs.setTabPosition(QTabWidget.TabPosition.North)
        try:
            tabs.tabBar().setExpanding(True)
        except Exception:
            pass

        self.general_tab = QWidget()
        self.general_tab.setMinimumHeight(0)
        self.general_tab.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        general_layout = QVBoxLayout(self.general_tab)
        general_layout.setContentsMargins(0, 0, 0, 0)
        general_layout.setSpacing(8)
        general_layout.addWidget(
            self._wrap_tab_content(self._build_compact_general_form()))

        self.prompting_tab = QWidget()
        self.prompting_tab.setMinimumHeight(0)
        self.prompting_tab.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        prompting_layout = QVBoxLayout(self.prompting_tab)
        prompting_layout.setContentsMargins(0, 0, 0, 0)
        prompting_layout.setSpacing(8)
        prompting_layout.addWidget(
            self._wrap_tab_content(self._build_prompting_form()))

        self.advanced_tab = QWidget()
        self.advanced_tab.setMinimumHeight(0)
        self.advanced_tab.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        advanced_layout = QVBoxLayout(self.advanced_tab)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)
        self.advanced_settings_form_container = self._build_advanced_form()
        self.advanced_settings_form_container.setMinimumHeight(0)
        self.advanced_settings_form_container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        advanced_layout.addWidget(self.advanced_settings_form_container)

        self.wd_tagger_tab = QWidget()
        self.wd_tagger_tab.setMinimumHeight(0)
        self.wd_tagger_tab.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        wd_layout = QVBoxLayout(self.wd_tagger_tab)
        wd_layout.setContentsMargins(0, 0, 0, 0)
        wd_layout.setSpacing(8)
        self.wd_tagger_settings_form_container = self._build_wd_tagger_form()
        wd_layout.addWidget(
            self._wrap_tab_content(self.wd_tagger_settings_form_container))

        tabs.addTab(self.general_tab, 'General')
        tabs.addTab(self.prompting_tab, 'Prompting')
        tabs.addTab(self.advanced_tab, 'Advanced')
        tabs.addTab(self.wd_tagger_tab, 'WD Tagger')
        self._sync_tab_visibility(self.model_combo_box.currentText())
        return tabs

    def _sync_tab_visibility(self, model_id: str):
        if self.tabs_widget is None:
            return
        is_wd_tagger_model = get_model_class(model_id) == WdTagger
        is_remote_model = get_model_class(model_id) == RemoteGen
        is_local_model = not is_wd_tagger_model and not is_remote_model
        for idx, visible in (
            (0, True),
            (1, not is_wd_tagger_model),
            (2, is_local_model),
            (3, is_wd_tagger_model),
        ):
            try:
                self.tabs_widget.setTabVisible(idx, visible)
            except Exception:
                try:
                    self.tabs_widget.widget(idx).setVisible(visible)
                except Exception:
                    pass

    def get_local_model_paths(self) -> list[str]:
        models_directory_path = settings.value(
            'models_directory_path',
            defaultValue=DEFAULT_SETTINGS['models_directory_path'], type=str)
        if not models_directory_path:
            return []
        models_directory_path = Path(models_directory_path)
        print(f'Loading local auto-captioning model paths under '
              f'{models_directory_path}...')
        config_paths = set(models_directory_path.glob('**/config.json'))
        selected_tags_paths = set(
            models_directory_path.glob('**/selected_tags.csv'))
        model_directory_paths = [str(path.parent) for path
                                 in config_paths | selected_tags_paths]
        model_directory_paths.sort()
        print(f'Loaded {len(model_directory_paths)} model '
              f'{pluralize("path", len(model_directory_paths))}.')
        return model_directory_paths

    @Slot(str)
    def show_settings_for_model(self, model_id: str):
        is_wd_tagger_model = get_model_class(model_id) == WdTagger
        is_remote_model = get_model_class(model_id) == RemoteGen
        is_local_model = not is_wd_tagger_model and not is_remote_model
        lowercase_id = model_id.lower()
        is_qwen_model = ('qwen2.5-vl' in lowercase_id
                         or 'qwen3.5' in lowercase_id)

        self.wd_tagger_settings_form_container.setVisible(is_wd_tagger_model)

        if self.use_compact_style:
            for widget in [self.system_prompt_container,
                           self.prompt_container,
                           self.skip_hash_container,
                           self.caption_start_container,
                           self.caption_position_combo_box,
                           self.remove_tag_separators_container,
                           self.remove_new_lines_container,
                           self.limit_to_crop_container]:
                widget.setVisible(not is_wd_tagger_model)
        else:
            for widget in [self.system_prompt_label, self.system_prompt_text_edit,
                           self.prompt_label, self.prompt_text_edit,
                           self.skip_hash_container,
                           self.caption_start_label, self.caption_start_line_edit,
                           self.remove_tag_separators_container,
                           self.remove_new_lines_container]:
                widget.setVisible(not is_wd_tagger_model)

        if self.use_compact_style:
            for widget in [self.load_in_4_bit_container,
                           self.advanced_settings_form_container]:
                widget.setVisible(is_local_model)
            if self.basic_settings_form is not None:
                self.basic_settings_form.setRowVisible(
                    self.device_combo_box, is_local_model)
                self.basic_settings_form.setRowVisible(
                    self.gpu_index_spin_box, is_local_model)
        else:
            for widget in [self.device_label, self.device_combo_box,
                           self.load_in_4_bit_container,
                           self.horizontal_line,
                           self.toggle_advanced_settings_form_button,
                           self.advanced_settings_form_container]:
                widget.setVisible(is_local_model)

        if self.tabs_widget is not None:
            self._sync_tab_visibility(model_id)

        self._apply_model_suggested_generation_defaults(model_id)

        if self.basic_settings_form is not None:
            self.basic_settings_form.setRowVisible(self.remote_address_line_edit, is_remote_model)
            self.basic_settings_form.setRowVisible(self.api_key_line_edit, is_remote_model)
            self.basic_settings_form.setRowVisible(self.api_model_line_edit, is_remote_model)
            self.basic_settings_form.setRowVisible(self.api_max_tokens_spin_box, is_remote_model)
            self.basic_settings_form.setRowVisible(
                self.video_fps_spin_box, is_remote_model or is_qwen_model)
            self.basic_settings_form.setRowVisible(
                self.video_max_frames_spin_box, is_remote_model or is_qwen_model)
        if self.basic_settings_form is not None:
            self.basic_settings_form.setRowVisible(
                self.disable_thinking_container, is_qwen_model)

        self.set_load_in_4_bit_visibility(self.device_combo_box.currentText())

    @Slot(str)
    def set_load_in_4_bit_visibility(self, device: str):
        model_id = self.model_combo_box.currentText()
        is_wd_tagger_model = get_model_class(model_id) == WdTagger
        is_remote_model = get_model_class(model_id) == RemoteGen
        if is_wd_tagger_model or is_remote_model:
            self.load_in_4_bit_container.setVisible(False)
            return
        is_load_in_4_bit_available = (self.is_bitsandbytes_available
                                      and device == CaptionDevice.GPU)
        self.load_in_4_bit_container.setVisible(is_load_in_4_bit_available)

    @Slot()
    def toggle_advanced_settings_form(self):
        if self.advanced_settings_form_container.isHidden():
            self.advanced_settings_form_container.show()
            self.toggle_advanced_settings_form_button.setText(
                'Hide Advanced Settings')
        else:
            self.advanced_settings_form_container.hide()
            self.toggle_advanced_settings_form_button.setText(
                'Show Advanced Settings')

    def get_caption_settings(self) -> dict:
        return {
            'model_id': self.model_combo_box.currentText(),
            'api_url': self.remote_address_line_edit.currentText(),
            'api_key': self.api_key_line_edit.text(),
            'api_model': self.api_model_line_edit.text(),
            'api_max_tokens': self.api_max_tokens_spin_box.value(),
            'video_fps': self.video_fps_spin_box.value(),
            'video_max_frames': self.video_max_frames_spin_box.value(),
            'disable_thinking': self.disable_thinking_check_box.isChecked(),
            'system_prompt': self.system_prompt_text_edit.toPlainText(),
            'prompt': self.prompt_text_edit.toPlainText(),
            'skip_hash': self.skip_hash_check_box.isChecked(),
            'caption_start': self.caption_start_line_edit.text(),
            'caption_position': self.caption_position_combo_box.currentText(),
            'device': self.device_combo_box.currentText(),
            'gpu_index': self.gpu_index_spin_box.value(),
            'load_in_4_bit': self.load_in_4_bit_check_box.isChecked(),
            'limit_to_crop': self.limit_to_crop_check_box.isChecked(),
            'remove_tag_separators':
                self.remove_tag_separators_check_box.isChecked(),
            'remove_new_lines': self.remove_new_lines_check_box.isChecked(),
            'bad_words': self.bad_words_line_edit.text(),
            'forced_words': self.forced_words_line_edit.text(),
            'generation_parameters': {
                'min_new_tokens': self.min_new_token_count_spin_box.value(),
                'max_new_tokens': self.max_new_token_count_spin_box.value(),
                'num_beams': self.beam_count_spin_box.value(),
                'length_penalty': self.length_penalty_spin_box.value(),
                'do_sample': self.use_sampling_check_box.isChecked(),
                'temperature': self.temperature_spin_box.value(),
                'top_k': self.top_k_spin_box.value(),
                'top_p': self.top_p_spin_box.value(),
                'repetition_penalty': self.repetition_penalty_spin_box.value(),
                'no_repeat_ngram_size':
                    self.no_repeat_ngram_size_spin_box.value()
            },
            'wd_tagger_settings': {
                'show_probabilities':
                    self.show_probabilities_check_box.isChecked(),
                'min_probability': self.min_probability_spin_box.value(),
                'max_tags': self.max_tags_spin_box.value(),
                'tags_to_exclude':
                    self.tags_to_exclude_text_edit.toPlainText()
            }
        }

@Slot()
def restore_stdout_and_stderr():
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__


class AutoCaptioner(QDockWidget):
    caption_generated = Signal(QModelIndex, str, list)
    layout_mode_changed = Signal(str)

    def __init__(self, image_list_model: ImageListModel,
                 image_list: ImageList,
                 image_viewer: 'ImageViewer' = None):
        super().__init__()
        self.image_list_model = image_list_model
        self.image_list = image_list
        self.image_viewer = image_viewer
        self.is_captioning = False
        self.captioning_thread = None
        self.processor = None
        self.model = None
        self.model_id: str | None = None
        self.model_device_type: str | None = None
        self.is_model_loaded_in_4_bit = None
        self.layout_mode = normalize_auto_captioner_layout_mode(
            load_auto_captioner_layout_mode())
        # Whether the last block of text in the console text edit should be
        # replaced with the next block of text that is outputted.
        self.replace_last_console_text_edit_block = False

        # Each `QDockWidget` needs a unique object name for saving its state.
        self.setObjectName('auto_captioner')
        self.setWindowTitle('Auto-Captioner')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)

        self.start_cancel_button = TallPushButton('Start Auto-Captioning')
        self.start_cancel_button.setObjectName('autoCaptionerPrimaryButton')
        self.start_cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat('%v / %m images captioned (%p%)')
        self.progress_bar.hide()
        self.console_text_edit = QPlainTextEdit()
        self.console_text_edit.setObjectName('autoCaptionerConsole')
        set_text_edit_height(self.console_text_edit, 4)
        self.console_text_edit.setReadOnly(True)
        self.console_text_edit.hide()
        self.classic_caption_settings_form = None
        self.compact_caption_settings_form = None
        self.caption_settings_form = None
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName('autoCaptionerScrollArea')
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.mode_container = QWidget()
        self.mode_container.setMinimumHeight(0)
        self.mode_container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.mode_layout = QVBoxLayout(self.mode_container)
        self.mode_layout.setContentsMargins(0, 0, 0, 0)
        self.mode_layout.setSpacing(0)
        self.setWidget(self.mode_container)
        self.set_layout_mode(self.layout_mode, persist=False)

        self.start_cancel_button.clicked.connect(
            self.start_or_cancel_captioning)

    def _connect_caption_history_buttons(self, form: CaptionSettingsForm):
        form.prompt_history_button.clicked.connect(self.show_prompt_history)
        form.system_prompt_history_button.clicked.connect(
            lambda: self.show_field_history(
                'system_prompt',
                form.system_prompt_text_edit,
                form.system_prompt_history_button))
        form.caption_start_history_button.clicked.connect(
            lambda: self.show_field_history(
                'caption_start',
                form.caption_start_line_edit,
                form.caption_start_history_button))
        form.bad_words_history_button.clicked.connect(
            lambda: self.show_field_history(
                'bad_words',
                form.bad_words_line_edit,
                form.bad_words_history_button))
        form.forced_words_history_button.clicked.connect(
            lambda: self.show_field_history(
                'forced_words',
                form.forced_words_line_edit,
                form.forced_words_history_button))

    def minimumSizeHint(self):
        base_hint = super().minimumSizeHint()
        if self.layout_mode == AUTO_CAPTIONER_LAYOUT_MODE_COMPACT:
            return QSize(max(160, base_hint.width()), 72)
        return base_hint

    def sizeHint(self):
        base_hint = super().sizeHint()
        if self.layout_mode == AUTO_CAPTIONER_LAYOUT_MODE_COMPACT:
            return QSize(max(220, base_hint.width()), max(160, base_hint.height()))
        return base_hint

    def set_layout_mode(self, layout_mode: str, *, persist: bool = True):
        normalized = normalize_auto_captioner_layout_mode(layout_mode)
        has_current_widget = self.mode_layout.count() > 0
        if normalized == self.layout_mode and has_current_widget:
            if persist:
                persist_auto_captioner_layout_mode(normalized)
            return

        self.caption_settings_form = CaptionSettingsForm(
            use_compact_style=(
                normalized == AUTO_CAPTIONER_LAYOUT_MODE_COMPACT
            )
        )
        if normalized == AUTO_CAPTIONER_LAYOUT_MODE_COMPACT:
            self.compact_caption_settings_form = self.caption_settings_form
        else:
            self.classic_caption_settings_form = self.caption_settings_form
        self._connect_caption_history_buttons(self.caption_settings_form)
        while self.mode_layout.count():
            item = self.mode_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        settings_page = self.caption_settings_form.build_page(normalized)
        if normalized == AUTO_CAPTIONER_LAYOUT_MODE_COMPACT:
            self.start_cancel_button.setMinimumWidth(0)
            self.start_cancel_button.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Fixed,
            )
        else:
            self.start_cancel_button.setMinimumWidth(0)
            self.start_cancel_button.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Fixed,
            )
        if normalized == AUTO_CAPTIONER_LAYOUT_MODE_COMPACT:
            root_page = QWidget()
            root_page.setMinimumHeight(0)
            root_page.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            root_layout = QVBoxLayout(root_page)
            root_page.setObjectName('autoCaptionerRootPage')
            root_layout.setContentsMargins(8, 8, 8, 8)
            root_layout.setSpacing(8)
            compact_content_scroll = QScrollArea()
            compact_content_scroll.setObjectName('autoCaptionerCompactContentScroll')
            compact_content_scroll.setWidgetResizable(True)
            compact_content_scroll.setFrameShape(QFrame.Shape.NoFrame)
            compact_content_scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            compact_content_scroll.setMinimumHeight(0)
            compact_content_scroll.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Ignored,
            )
            compact_content_scroll.setWidget(settings_page)
            root_layout.addWidget(self.start_cancel_button)
            root_layout.addWidget(self.progress_bar)
            root_layout.addWidget(self.console_text_edit)
            root_layout.addWidget(compact_content_scroll, 1)
            self.mode_layout.addWidget(root_page)
            self._apply_layout_style(root_page, normalized)
        else:
            root_page = QWidget()
            root_layout = QVBoxLayout(root_page)
            root_layout.addWidget(self.start_cancel_button)
            root_layout.addWidget(self.progress_bar)
            root_layout.addWidget(self.console_text_edit)
            root_layout.addWidget(settings_page)
            root_layout.addStretch(1)
            self.scroll_area.takeWidget()
            self.scroll_area.setWidget(root_page)
            self.mode_layout.addWidget(self.scroll_area)
            self._apply_layout_style(root_page, normalized)
        self.layout_mode = normalized
        self._update_primary_button_text()
        self.updateGeometry()
        if persist:
            persist_auto_captioner_layout_mode(normalized)
        self.layout_mode_changed.emit(normalized)

    def _apply_layout_style(self, root_page: QWidget, layout_mode: str):
        if layout_mode != AUTO_CAPTIONER_LAYOUT_MODE_COMPACT:
            self.mode_container.setStyleSheet('')
            root_page.setStyleSheet('')
            return

        assets_dir = (Path(__file__).resolve().parent.parent
                      / 'assets' / 'auto_captioner')
        combo_arrow_path = (assets_dir / 'chevron-down.svg').as_posix()
        spin_up_arrow_path = (assets_dir / 'chevron-up-small.svg').as_posix()
        spin_down_arrow_path = (assets_dir / 'chevron-down-small.svg').as_posix()

        self.mode_container.setStyleSheet(
            'QWidget { background: #2b2b2b; }'
            'QScrollArea { border: none; background: transparent; }'
            'QScrollArea > QWidget > QWidget { background: transparent; }'
        )
        root_page.setStyleSheet(
            'QWidget#autoCaptionerRootPage {'
            '  background: #2b2b2b;'
            '  color: #f3f4f6;'
            '  font-family: "Segoe UI", Arial, sans-serif;'
            '  font-size: 12px;'
            '}'
            'QPushButton#autoCaptionerPrimaryButton {'
            '  background-color: #3b82f6;'
            '  color: #ffffff;'
            '  border: none;'
            '  border-radius: 6px;'
            '  padding: 6px 10px;'
            '  min-height: 28px;'
            '  max-height: 30px;'
            '  font-size: 11px;'
            '  font-weight: 600;'
            '}'
            'QPushButton#autoCaptionerPrimaryButton:hover {'
            '  background-color: #2563eb;'
            '}'
            'QPushButton#autoCaptionerSecondaryButton {'
            '  background: transparent;'
            '  color: #d1d5db;'
            '  border: 1px solid #4b5563;'
            '  border-radius: 6px;'
            '  padding: 5px 10px;'
            '  min-height: 26px;'
            '  font-size: 11px;'
            '  font-weight: 600;'
            '}'
            'QPushButton#autoCaptionerSecondaryButton:hover {'
            '  background: #353847;'
            '  border-color: #6b7280;'
            '  color: #f3f4f6;'
            '}'
            'QProgressBar {'
            '  border: 1px solid #4b5563;'
            '  border-radius: 4px;'
            '  background: #1e1e24;'
            '  color: #f3f4f6;'
            '  text-align: center;'
            '  font-size: 12px;'
            '}'
            'QProgressBar::chunk {'
            '  background-color: #3b82f6;'
            '  border-radius: 3px;'
            '}'
            'QPlainTextEdit#autoCaptionerConsole {'
            '  background: #1e1e24;'
            '  color: #f3f4f6;'
            '  border: 1px solid #4b5563;'
            '  border-radius: 4px;'
            '  font-size: 12px;'
            '}'
            'QPlainTextEdit QScrollBar:vertical {'
            '  background: transparent;'
            '  width: 8px;'
            '  margin: 2px 2px 2px 0px;'
            '}'
            'QPlainTextEdit QScrollBar::handle:vertical {'
            '  background: #5b6472;'
            '  border-radius: 4px;'
            '  min-height: 24px;'
            '}'
            'QPlainTextEdit QScrollBar::handle:vertical:hover {'
            '  background: #728096;'
            '}'
            'QPlainTextEdit QScrollBar::add-line:vertical, '
            'QPlainTextEdit QScrollBar::sub-line:vertical, '
            'QPlainTextEdit QScrollBar::add-page:vertical, '
            'QPlainTextEdit QScrollBar::sub-page:vertical {'
            '  background: transparent;'
            '  border: none;'
            '  height: 0px;'
            '}'
            'QTabWidget::pane {'
            '  border: none;'
            '}'
            'QScrollArea#autoCaptionerTabScrollArea {'
            '  border: none;'
            '  background: transparent;'
            '}'
            'QScrollArea#autoCaptionerTabScrollArea > QWidget > QWidget {'
            '  background: transparent;'
            '}'
            'QScrollArea#autoCaptionerCompactContentScroll {'
            '  border: none;'
            '  background: transparent;'
            '}'
            'QScrollArea#autoCaptionerCompactContentScroll > QWidget > QWidget {'
            '  background: transparent;'
            '}'
            'QTabBar {'
            '  qproperty-drawBase: 0;'
            '}'
            'QTabBar::tab {'
            '  background: transparent;'
            '  color: #9ca3af;'
            '  border: none;'
            '  border-bottom: 2px solid transparent;'
            '  padding: 5px 8px;'
            '  margin-right: 4px;'
            '  min-height: 22px;'
            '  font-size: 11px;'
            '  font-weight: 500;'
            '}'
            'QTabBar::tab:selected {'
            '  color: #60a5fa;'
            '  border-bottom-color: #3b82f6;'
            '}'
            'QTabBar::tab:hover {'
            '  color: #e5e7eb;'
            '}'
            'QLabel[autoCaptionerFieldLabel="true"] {'
            '  color: #d1d5db;'
            '  font-size: 12px;'
            '  font-weight: 500;'
            '}'
            'QLineEdit, QComboBox, QPlainTextEdit {'
            '  background: #1e1e24;'
            '  color: #f3f4f6;'
            '  border: 1px solid #4b5563;'
            '  border-radius: 4px;'
            '  padding: 6px 8px;'
            '  padding-right: 24px;'
            '  min-height: 30px;'
            '  selection-background-color: #3b82f6;'
            '  font-size: 12px;'
            '}'
            'QSpinBox, QDoubleSpinBox {'
            '  background: #1e1e24;'
            '  color: #f3f4f6;'
            '  border: 1px solid #4b5563;'
            '  border-radius: 4px;'
            '  padding: 4px 8px;'
            '  padding-right: 20px;'
            '  min-height: 30px;'
            '  selection-background-color: #3b82f6;'
            '  font-size: 12px;'
            '}'
            'QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {'
            '  border: 1px solid #3b82f6;'
            '}'
            'QComboBox::drop-down {'
            '  border: none;'
            '  width: 22px;'
            '  subcontrol-origin: padding;'
            '  subcontrol-position: top right;'
            '}'
            f'QComboBox::down-arrow {{'
            f'  image: url("{combo_arrow_path}");'
            '  width: 12px;'
            '  height: 12px;'
            '}'
            'QSpinBox::up-button, QDoubleSpinBox::up-button {'
            '  subcontrol-origin: border;'
            '  subcontrol-position: top right;'
            '  width: 16px;'
            '  border: none;'
            '  background: transparent;'
            '}'
            'QSpinBox::down-button, QDoubleSpinBox::down-button {'
            '  subcontrol-origin: border;'
            '  subcontrol-position: bottom right;'
            '  width: 16px;'
            '  border: none;'
            '  background: transparent;'
            '}'
            f'QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{'
            f'  image: url("{spin_up_arrow_path}");'
            '  width: 8px;'
            '  height: 8px;'
            '}'
            f'QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{'
            f'  image: url("{spin_down_arrow_path}");'
            '  width: 8px;'
            '  height: 8px;'
            '}'
            'QComboBox QAbstractItemView {'
            '  background: #1e1e24;'
            '  color: #f3f4f6;'
            '  selection-background-color: #3b82f6;'
            '}'
            'QCheckBox {'
            '  color: #d1d5db;'
            '  font-size: 12px;'
            '  spacing: 8px;'
            '}'
            'QCheckBox::indicator {'
            '  width: 38px;'
            '  height: 20px;'
            '  border-radius: 10px;'
            '  background: #374151;'
            '  border: 1px solid #4b5563;'
            '}'
            'QCheckBox::indicator:checked {'
            '  background: #3b82f6;'
            '  border-color: #3b82f6;'
            '}'
        )

    @Slot()
    def start_or_cancel_captioning(self):
        if self.is_captioning:
            # Cancel captioning.
            self.captioning_thread.is_canceled = True
            self.start_cancel_button.setEnabled(False)
            self._update_primary_button_text(canceling=True)
        else:
            # Start captioning.
            self.generate_captions()

    def set_is_captioning(self, is_captioning: bool):
        self.is_captioning = is_captioning
        self._update_primary_button_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_primary_button_text()

    def _update_primary_button_text(self, *, canceling: bool = False):
        if canceling:
            full_text = 'Canceling Auto-Captioning...'
            medium_text = 'Canceling...'
            compact_text = 'Cancel'
        elif self.is_captioning:
            full_text = 'Cancel Auto-Captioning'
            medium_text = 'Cancel Captioning'
            compact_text = 'Cancel'
        else:
            full_text = 'Start Auto-Captioning'
            medium_text = 'Start Captioning'
            compact_text = 'Start'

        if self.layout_mode != AUTO_CAPTIONER_LAYOUT_MODE_COMPACT:
            self.start_cancel_button.setText(full_text)
            return

        available_width = self.start_cancel_button.width()
        if available_width >= 210:
            self.start_cancel_button.setText(full_text)
        elif available_width >= 150:
            self.start_cancel_button.setText(medium_text)
        else:
            self.start_cancel_button.setText(compact_text)

    @Slot(str)
    def update_console_text_edit(self, text: str):
        # '\x1b[A' is the ANSI escape sequence for moving the cursor up.
        if text == '\x1b[A':
            self.replace_last_console_text_edit_block = True
            return
        text = text.strip()
        if not text:
            return
        if self.console_text_edit.isHidden():
            self.console_text_edit.show()
        if self.replace_last_console_text_edit_block:
            self.replace_last_console_text_edit_block = False
            # Select and remove the last block of text.
            self.console_text_edit.moveCursor(QTextCursor.MoveOperation.End)
            self.console_text_edit.moveCursor(
                QTextCursor.MoveOperation.StartOfBlock,
                QTextCursor.MoveMode.KeepAnchor)
            self.console_text_edit.textCursor().removeSelectedText()
            # Delete the newline.
            self.console_text_edit.textCursor().deletePreviousChar()
        self.console_text_edit.appendPlainText(text)

    @Slot()
    def show_alert(self):
        if self.captioning_thread.is_canceled:
            return
        if self.captioning_thread.is_error:
            icon = QMessageBox.Icon.Critical
            text = ('An error occurred during captioning. See the '
                    'Auto-Captioner console for more information.')
        else:
            icon = QMessageBox.Icon.Information
            text = 'Captioning has finished.'
        alert = QMessageBox()
        alert.setIcon(icon)
        alert.setText(text)
        alert.exec()

    @Slot()
    def show_prompt_history(self):
        """Show prompt history dialog."""
        dialog = PromptHistoryDialog(self)
        dialog.prompt_selected.connect(self.load_prompt_from_history)
        dialog.exec()

    @Slot(str)
    def load_prompt_from_history(self, prompt: str):
        """Load a prompt from history into the prompt field."""
        self.caption_settings_form.prompt_text_edit.setPlainText(prompt)

    def show_field_history(self, field_key: str, line_edit, button):
        """Show field history popup menu."""
        popup = FieldHistoryPopup(field_key, line_edit)
        if hasattr(line_edit, 'setPlainText'):
            popup.value_selected.connect(line_edit.setPlainText)
        else:
            popup.value_selected.connect(line_edit.setText)

        # Position popup below the button
        pos = button.mapToGlobal(button.rect().bottomLeft())
        popup.popup(pos)

    @Slot()
    def generate_captions(self):
        # Save current prompt to history before generating captions
        current_prompt = self.caption_settings_form.prompt_text_edit.toPlainText()
        if current_prompt and current_prompt.strip():
            history = get_prompt_history()
            history.add_prompt(current_prompt.strip())

        # Save field values to history
        field_history = get_field_history()

        remote_address = self.caption_settings_form.remote_address_line_edit.currentText()
        if remote_address and remote_address.strip():
            field_history.add_value('remote_address', remote_address.strip())
            
        api_model = self.caption_settings_form.api_model_line_edit.text()
        if api_model and api_model.strip():
            field_history.add_value('api_model', api_model.strip())

        caption_start = self.caption_settings_form.caption_start_line_edit.text()
        if caption_start and caption_start.strip():
            field_history.add_value('caption_start', caption_start.strip())

        bad_words = self.caption_settings_form.bad_words_line_edit.text()
        if bad_words and bad_words.strip():
            field_history.add_value('bad_words', bad_words.strip())

        forced_words = self.caption_settings_form.forced_words_line_edit.text()
        if forced_words and forced_words.strip():
            field_history.add_value('forced_words', forced_words.strip())

        selected_image_indices = self.image_list.get_selected_image_indices()
        selected_image_count = len(selected_image_indices)
        show_alert_when_finished = False
        if selected_image_count > 1:
            confirmation_dialog = CaptionMultipleImagesDialog(
                selected_image_count)
            reply = confirmation_dialog.exec()
            if reply != QMessageBox.StandardButton.Yes:
                return
            show_alert_when_finished = (confirmation_dialog
                                        .show_alert_check_box.isChecked())
        self.set_is_captioning(True)
        caption_settings = self.caption_settings_form.get_caption_settings()
        if caption_settings['caption_position'] != CaptionPosition.DO_NOT_ADD:
            self.image_list_model.add_to_undo_stack(
                action_name=f'Generate '
                            f'{pluralize("Caption", selected_image_count)}',
                should_ask_for_confirmation=selected_image_count > 1)
        if selected_image_count > 1:
            self.progress_bar.setRange(0, selected_image_count)
            self.progress_bar.setValue(0)
            self.progress_bar.show()
        tag_separator = get_tag_separator()
        models_directory_path = settings.value(
            'models_directory_path',
            defaultValue=DEFAULT_SETTINGS['models_directory_path'], type=str)
        models_directory_path = (Path(models_directory_path)
                                 if models_directory_path else None)
        self.captioning_thread = CaptioningThread(
            self, self.image_list_model, selected_image_indices,
            caption_settings, tag_separator, models_directory_path,
            self.image_viewer)
        self.captioning_thread.text_outputted.connect(
            self.update_console_text_edit)
        self.captioning_thread.clear_console_text_edit_requested.connect(
            self.console_text_edit.clear)
        self.captioning_thread.caption_generated.connect(
            self.caption_generated)
        self.captioning_thread.progress_bar_update_requested.connect(
            self.progress_bar.setValue)
        self.captioning_thread.finished.connect(
            lambda: self.set_is_captioning(False))
        self.captioning_thread.finished.connect(restore_stdout_and_stderr)
        self.captioning_thread.finished.connect(self.progress_bar.hide)
        self.captioning_thread.finished.connect(
            lambda: self.start_cancel_button.setEnabled(True))
        if show_alert_when_finished:
            self.captioning_thread.finished.connect(self.show_alert)
        # Redirect `stdout` and `stderr` so that the outputs are displayed in
        # the console text edit.
        sys.stdout = self.captioning_thread
        sys.stderr = self.captioning_thread
        self.captioning_thread.start()
