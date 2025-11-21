from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout, QComboBox,
                               QScrollArea, QWidget, QTabWidget)

from utils.settings import DEFAULT_SETTINGS, settings
from utils.settings_widgets import (SettingsBigCheckBox, SettingsLineEdit,
                                    SettingsSpinBox)
from utils.grammar_checker import GrammarCheckMode


class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Settings')

        # Main layout for dialog
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Create tab widget
        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)

        # Create tabs
        tab_widget.addTab(self._create_general_tab(), 'General')
        tab_widget.addTab(self._create_models_tab(), 'Models')
        tab_widget.addTab(self._create_cache_tab(), 'Cache')
        tab_widget.addTab(self._create_spell_check_tab(), 'Spell Check')
        tab_widget.addTab(self._create_advanced_tab(), 'Advanced')

        # Restart warning at bottom of main dialog
        self.restart_warning = ('Restart the application to apply the new '
                                'settings.')
        self.warning_label = QLabel(self.restart_warning)
        self.warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.warning_label.setStyleSheet('color: red;')
        main_layout.addWidget(self.warning_label)

        # Fix the size of the dialog to its size when the warning label is shown.
        self.setFixedSize(self.sizeHint())
        self.warning_label.hide()

    def _create_general_tab(self):
        """Create General settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        grid_layout = QGridLayout()

        # Font size
        grid_layout.addWidget(QLabel('Font size (pt)'), 0, 0,
                              Qt.AlignmentFlag.AlignRight)
        font_size_spin_box = SettingsSpinBox(
            key='font_size',
            minimum=1, maximum=99)
        font_size_spin_box.valueChanged.connect(self.show_restart_warning)
        grid_layout.addWidget(font_size_spin_box, 0, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # File types
        grid_layout.addWidget(QLabel('File types to show in image list'), 1, 0,
                              Qt.AlignmentFlag.AlignRight)
        file_types_line_edit = SettingsLineEdit(
            key='image_list_file_formats')
        file_types_line_edit.setMinimumWidth(400)
        file_types_line_edit.textChanged.connect(self.show_restart_warning)
        grid_layout.addWidget(file_types_line_edit, 1, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Image width
        grid_layout.addWidget(QLabel('Image width in image list (px)'), 2, 0,
                              Qt.AlignmentFlag.AlignRight)
        image_list_image_width_spin_box = SettingsSpinBox(
            key='image_list_image_width',
            minimum=16, maximum=9999)
        image_list_image_width_spin_box.valueChanged.connect(
            self.show_restart_warning)
        grid_layout.addWidget(image_list_image_width_spin_box, 2, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Insert space after separator (create first, needed by tag separator handler)
        grid_layout.addWidget(QLabel('Insert space after tag separator'), 4, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.insert_space_after_tag_separator_check_box = SettingsBigCheckBox(
            key='insert_space_after_tag_separator')
        self.insert_space_after_tag_separator_check_box.stateChanged.connect(
            self.show_restart_warning)
        grid_layout.addWidget(self.insert_space_after_tag_separator_check_box,
                              4, 1, Qt.AlignmentFlag.AlignLeft)

        # Tag separator (must be after checkbox creation)
        grid_layout.addWidget(QLabel('Tag separator (\\n for newline)'), 3, 0,
                              Qt.AlignmentFlag.AlignRight)
        tag_separator_line_edit = QLineEdit()
        tag_separator = settings.value(
            'tag_separator', defaultValue=DEFAULT_SETTINGS['tag_separator'],
            type=str)
        if tag_separator == '\n':
            tag_separator = r'\n'
            self.disable_insert_space_after_tag_separator_check_box()
        tag_separator_line_edit.setMaximumWidth(50)
        tag_separator_line_edit.setText(tag_separator)
        tag_separator_line_edit.textChanged.connect(
            self.handle_tag_separator_change)
        grid_layout.addWidget(tag_separator_line_edit, 3, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Autocomplete
        grid_layout.addWidget(QLabel('Show tag autocomplete suggestions'),
                              5, 0, Qt.AlignmentFlag.AlignRight)
        autocomplete_tags_check_box = SettingsBigCheckBox(
            key='autocomplete_tags')
        autocomplete_tags_check_box.stateChanged.connect(
            self.show_restart_warning)
        grid_layout.addWidget(autocomplete_tags_check_box, 5, 1,
                              Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(grid_layout)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    def _create_models_tab(self):
        """Create Models settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        grid_layout = QGridLayout()

        # Auto-captioning models directory
        grid_layout.addWidget(QLabel('Auto-captioning models directory'), 0, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.models_directory_line_edit = SettingsLineEdit(
            key='models_directory_path')
        self.models_directory_line_edit.setMinimumWidth(400)
        self.models_directory_line_edit.setClearButtonEnabled(True)
        self.models_directory_line_edit.textChanged.connect(
            self.show_restart_warning)
        grid_layout.addWidget(self.models_directory_line_edit, 0, 1,
                              Qt.AlignmentFlag.AlignLeft)

        models_directory_button = QPushButton('Select Directory...')
        models_directory_button.setFixedWidth(
            int(models_directory_button.sizeHint().width() * 1.3))
        models_directory_button.clicked.connect(self.set_models_directory_path)
        grid_layout.addWidget(models_directory_button, 1, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Auto-marking models directory
        grid_layout.addWidget(QLabel('Auto-marking models directory'), 2, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.marking_models_directory_line_edit = SettingsLineEdit(
            key='marking_models_directory_path')
        self.marking_models_directory_line_edit.setMinimumWidth(400)
        self.marking_models_directory_line_edit.setClearButtonEnabled(True)
        grid_layout.addWidget(self.marking_models_directory_line_edit, 2, 1,
                              Qt.AlignmentFlag.AlignLeft)

        marking_models_directory_button = QPushButton('Select Directory...')
        marking_models_directory_button.setFixedWidth(
            int(marking_models_directory_button.sizeHint().width() * 1.3))
        marking_models_directory_button.clicked.connect(
            self.set_marking_models_directory_path)
        grid_layout.addWidget(marking_models_directory_button, 3, 1,
                              Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(grid_layout)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    def _create_cache_tab(self):
        """Create Cache settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        grid_layout = QGridLayout()

        # Enable dimension cache
        grid_layout.addWidget(QLabel('Enable dimension cache (.taggui_index.db)'), 0, 0,
                              Qt.AlignmentFlag.AlignRight)
        enable_dimension_cache_check_box = SettingsBigCheckBox(
            key='enable_dimension_cache')
        enable_dimension_cache_check_box.setToolTip(
            'Cache image dimensions in .taggui_index.db files for instant folder reloads')
        grid_layout.addWidget(enable_dimension_cache_check_box, 0, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Enable thumbnail cache
        grid_layout.addWidget(QLabel('Enable thumbnail cache'), 1, 0,
                              Qt.AlignmentFlag.AlignRight)
        enable_thumbnail_cache_check_box = SettingsBigCheckBox(
            key='enable_thumbnail_cache')
        enable_thumbnail_cache_check_box.setToolTip(
            'Cache generated thumbnails to disk for instant display on reload')
        grid_layout.addWidget(enable_thumbnail_cache_check_box, 1, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Thumbnail cache location
        grid_layout.addWidget(QLabel('Thumbnail cache location'), 2, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.thumbnail_cache_location_line_edit = SettingsLineEdit(
            key='thumbnail_cache_location')
        self.thumbnail_cache_location_line_edit.setMinimumWidth(400)
        self.thumbnail_cache_location_line_edit.setPlaceholderText(
            'Default: ~/.taggui_cache/thumbnails')
        self.thumbnail_cache_location_line_edit.setToolTip(
            'Leave empty for default location. Change to move cache to custom directory.')
        grid_layout.addWidget(self.thumbnail_cache_location_line_edit, 2, 1,
                              Qt.AlignmentFlag.AlignLeft)

        thumbnail_cache_location_button = QPushButton('Browse...')
        thumbnail_cache_location_button.clicked.connect(
            self.choose_thumbnail_cache_location)
        grid_layout.addWidget(thumbnail_cache_location_button, 3, 1,
                              Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(grid_layout)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    def _create_spell_check_tab(self):
        """Create Spell Check settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        grid_layout = QGridLayout()

        # Enable spell checking
        grid_layout.addWidget(QLabel('Enable spell checking'), 0, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.spell_check_enabled = SettingsBigCheckBox(
            key='spell_check_enabled',
            default=True)
        self.spell_check_enabled.stateChanged.connect(self.show_restart_warning)
        grid_layout.addWidget(self.spell_check_enabled, 0, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Grammar check mode
        grid_layout.addWidget(QLabel('Grammar check mode'), 1, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.grammar_check_mode_combo = QComboBox()
        self.grammar_check_mode_combo.addItem('Disabled', GrammarCheckMode.DISABLED.value)
        self.grammar_check_mode_combo.addItem('Free API (20 req/min)', GrammarCheckMode.FREE_API.value)
        self.grammar_check_mode_combo.addItem('Local Server (requires Java)', GrammarCheckMode.LOCAL_SERVER.value)

        # Load current grammar check mode
        current_mode = settings.value('grammar_check_mode',
                                     defaultValue=GrammarCheckMode.FREE_API.value,
                                     type=str)
        for i in range(self.grammar_check_mode_combo.count()):
            if self.grammar_check_mode_combo.itemData(i) == current_mode:
                self.grammar_check_mode_combo.setCurrentIndex(i)
                break

        self.grammar_check_mode_combo.currentIndexChanged.connect(
            lambda: self._save_grammar_mode())
        grid_layout.addWidget(self.grammar_check_mode_combo, 1, 1,
                              Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(grid_layout)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    def _create_advanced_tab(self):
        """Create Advanced settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        grid_layout = QGridLayout()

        # Trainer target resolution
        grid_layout.addWidget(QLabel('Trainer target resolution (for exact bucket snap)'), 0, 0,
                              Qt.AlignmentFlag.AlignRight)
        trainer_target_resolution_spin_box = SettingsSpinBox(
            key='trainer_target_resolution',
            minimum=256, maximum=4096)
        trainer_target_resolution_spin_box.setToolTip(
            'Set your trainer\'s target resolution (e.g., 1024 for 1024x1024). '
            'Use Shift+Ctrl+drag to snap crops to exact buckets for this resolution.')
        grid_layout.addWidget(trainer_target_resolution_spin_box, 0, 1,
                              Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(grid_layout)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    @Slot()
    def show_restart_warning(self):
        self.warning_label.setText(self.restart_warning)
        self.warning_label.show()

    def disable_insert_space_after_tag_separator_check_box(self):
        self.insert_space_after_tag_separator_check_box.setEnabled(False)
        self.insert_space_after_tag_separator_check_box.setChecked(False)

    @Slot(str)
    def handle_tag_separator_change(self, tag_separator: str):
        if not tag_separator:
            self.warning_label.setText('The tag separator cannot be empty.')
            self.warning_label.show()
            return
        if tag_separator == r'\n':
            tag_separator = '\n'
            self.disable_insert_space_after_tag_separator_check_box()
        else:
            self.insert_space_after_tag_separator_check_box.setEnabled(True)
        settings.setValue('tag_separator', tag_separator)
        self.show_restart_warning()

    @Slot()
    def choose_thumbnail_cache_location(self):
        """Browse for thumbnail cache directory."""
        current_location = settings.value(
            'thumbnail_cache_location',
            defaultValue=DEFAULT_SETTINGS['thumbnail_cache_location'], type=str)

        if not current_location:
            # Use default location as starting point
            from pathlib import Path
            current_location = str(Path.home() / '.taggui_cache' / 'thumbnails')

        directory = QFileDialog.getExistingDirectory(
            self, 'Select Thumbnail Cache Location', current_location)

        if directory:
            self.thumbnail_cache_location_line_edit.setText(directory)
            settings.setValue('thumbnail_cache_location', directory)

    @Slot()
    def set_models_directory_path(self):
        models_directory_path = settings.value(
            'models_directory_path',
            defaultValue=DEFAULT_SETTINGS['models_directory_path'], type=str)
        if models_directory_path:
            initial_directory_path = models_directory_path
        elif settings.contains('directory_path'):
            initial_directory_path = settings.value('directory_path', type=str)
        else:
            initial_directory_path = ''
        models_directory_path = QFileDialog.getExistingDirectory(
            parent=self, caption='Select directory containing auto-captioning '
                                 'models',
            dir=initial_directory_path)
        if models_directory_path:
            self.models_directory_line_edit.setText(models_directory_path)

    @Slot()
    def set_marking_models_directory_path(self):
        marking_models_directory_path = settings.value(
            'marking_models_directory_path',
            defaultValue=DEFAULT_SETTINGS['marking_models_directory_path'], type=str)
        if marking_models_directory_path:
            initial_directory_path = marking_models_directory_path
        elif settings.contains('directory_path'):
            initial_directory_path = settings.value('directory_path', type=str)
        else:
            initial_directory_path = ''
        marking_models_directory_path = QFileDialog.getExistingDirectory(
            parent=self, caption='Select directory containing auto-marking '
                                 'models (YOLO models)',
            dir=initial_directory_path)
        if marking_models_directory_path:
            self.marking_models_directory_line_edit.setText(marking_models_directory_path)

    @Slot()
    def _save_grammar_mode(self):
        """Save the selected grammar check mode to settings."""
        mode_value = self.grammar_check_mode_combo.currentData()
        settings.setValue('grammar_check_mode', mode_value)
        self.show_restart_warning()
