from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout, QComboBox,
                               QScrollArea, QWidget, QTabWidget, QMessageBox, QHBoxLayout)

from pathlib import Path
import shutil
from utils.settings import DEFAULT_SETTINGS, settings
from utils.settings_widgets import (SettingsBigCheckBox, SettingsLineEdit,
                                    SettingsSpinBox, SettingsComboBox)
from utils.grammar_checker import GrammarCheckMode
from utils.thumbnail_cache import get_thumbnail_cache


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

        # Restore last selected tab
        last_tab = settings.value('settings_dialog_last_tab', defaultValue=0, type=int)
        if 0 <= last_tab < tab_widget.count():
            tab_widget.setCurrentIndex(last_tab)

        # Save tab index when changed
        tab_widget.currentChanged.connect(
            lambda index: settings.setValue('settings_dialog_last_tab', index)
        )

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

        # Pagination threshold
        grid_layout.addWidget(QLabel('Paginate folders larger than (images)'), 6, 0,
                              Qt.AlignmentFlag.AlignRight)
        pagination_spin_box = SettingsSpinBox(
            key='pagination_threshold',
            minimum=0, maximum=100000)
        pagination_spin_box.setToolTip(
            'Enable pagination mode for folders with more than this many images.\n\n'
            'Pagination mode loads thumbnails on-demand as you scroll, keeping only\n'
            'visible + nearby thumbnails in memory. This enables smooth scrolling\n'
            'with datasets of any size (even 1M+ images).\n\n'
            'Setting this to 0 (recommended):\n'
            'Always use pagination mode for consistent performance regardless of folder size.\n'
            'Pagination is now highly optimized with low-priority background saves and\n'
            'minimal overhead - it works smoothly even for small folders.\n\n'
            'Setting this higher (e.g., 500, 1000, 5000):\n'
            'Only paginate when folders exceed this size. Smaller folders will load\n'
            'all thumbnails at once (classic mode). This may cause UI freezes and\n'
            'memory issues with large folders if threshold is set too high.')
        pagination_spin_box.valueChanged.connect(self.show_restart_warning)
        grid_layout.addWidget(pagination_spin_box, 6, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Masonry strategy
        grid_layout.addWidget(QLabel('Masonry strategy'), 7, 0,
                              Qt.AlignmentFlag.AlignRight)
        masonry_strategy_combo = SettingsComboBox(
            key='masonry_strategy',
            default='full_compat')
        masonry_strategy_combo.addItems(['full_compat', 'windowed_strict'])
        masonry_strategy_combo.setToolTip(
            'Select masonry engine behavior for paginated mode.\n\n'
            'full_compat:\n'
            '- Stable/default behavior.\n'
            '- Allows full masonry fallback when coverage is high.\n\n'
            'windowed_strict:\n'
            '- Experimental true paginated behavior for very large datasets.\n'
            '- Keeps masonry calculation window-local (no full fallback).\n\n'
            'If the UI is already open, changing this takes effect on the next masonry recalculation.'
        )
        grid_layout.addWidget(masonry_strategy_combo, 7, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Thumbnail eviction pages (VRAM behavior in paginated mode)
        grid_layout.addWidget(QLabel('Thumbnail eviction pages (VRAM)'), 8, 0,
                              Qt.AlignmentFlag.AlignRight)
        eviction_pages_spin_box = SettingsSpinBox(
            key='thumbnail_eviction_pages',
            minimum=1, maximum=5)
        eviction_pages_spin_box.setToolTip(
            'How many pages around the viewport keep thumbnails resident.\n'
            '1 = lower VRAM, more refill/pop-in\n'
            '3 = balanced default\n'
            '5 = higher VRAM, smoother revisits\n'
            'Applied live.')
        grid_layout.addWidget(eviction_pages_spin_box, 8, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Max pages in memory (page object budget for paginated mode)
        grid_layout.addWidget(QLabel('Max pages in memory (RAM)'), 9, 0,
                              Qt.AlignmentFlag.AlignRight)
        max_pages_spin_box = SettingsSpinBox(
            key='max_pages_in_memory',
            minimum=3, maximum=60, default=20)
        max_pages_spin_box.setToolTip(
            'Maximum paginated pages kept in RAM.\n'
            'Lower = less RAM, more refetch on jumps\n'
            'Higher = smoother revisits, more RAM use\n'
            'Guardrail: effective value is at least (2 * eviction pages + 1).\n'
            'Applied live.')
        grid_layout.addWidget(max_pages_spin_box, 9, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Video player skin
        grid_layout.addWidget(QLabel('Video player skin'), 10, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.video_skin_combo = SettingsComboBox(
            key='video_player_skin',
            default='Classic')

        # Populate with available skins
        from skins.engine import SkinManager
        skin_manager = SkinManager()
        available_skins = skin_manager.get_available_skins()
        skin_names = [skin['name'] for skin in available_skins]
        if skin_names:
            self.video_skin_combo.addItems(skin_names)
        else:
            self.video_skin_combo.addItem('Modern Dark')  # Fallback

        self.video_skin_combo.setToolTip(
            'Choose visual theme for video player controls.\n\n'
            'Skins change colors, spacing, and appearance of:\n'
            '- Control bar and buttons\n'
            '- Timeline slider and loop markers\n'
            '- Speed slider gradient\n\n'
            'Changes apply instantly when you switch skins.\n'
            'Create custom skins in taggui/skins/user/ folder.')

        # Apply skin changes immediately (no restart needed!)
        self.video_skin_combo.currentTextChanged.connect(self._on_skin_changed)

        grid_layout.addWidget(self.video_skin_combo, 10, 1,
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

        # Cache management section (continue grid layout)
        grid_layout.addWidget(QLabel(''), 4, 0)  # Spacer row

        grid_layout.addWidget(QLabel('Cache Management'), 5, 0,
                              Qt.AlignmentFlag.AlignRight)

        cache_buttons_layout = QVBoxLayout()
        cache_buttons_layout.setSpacing(10)

        # Clear current directory cache button
        self.clear_current_button = QPushButton('Clear Current Directory Cache')
        self.clear_current_button.setToolTip(
            'Delete dimension cache (.taggui_index.db) and thumbnails for the currently loaded directory only')
        self.clear_current_button.clicked.connect(self.clear_current_directory_cache)

        # Size label and calculate button for current directory
        self.clear_current_size_label = QLabel('(click to calculate)')
        self.clear_current_size_label.setStyleSheet('color: #666; font-size: 10px; margin-left: 10px;')

        self.calc_current_size_button = QPushButton('Calculate')
        self.calc_current_size_button.setToolTip('Calculate cache size for current directory')
        self.calc_current_size_button.clicked.connect(self._calculate_current_directory_size)

        # Current directory row (button + size + calc)
        current_row_layout = QHBoxLayout()
        current_row_layout.setSpacing(10)
        current_row_layout.addWidget(self.clear_current_button)
        current_row_layout.addWidget(self.clear_current_size_label)
        current_row_layout.addWidget(self.calc_current_size_button)
        current_row_layout.addStretch()

        # Clear all cache button
        self.clear_all_button = QPushButton('Clear All Thumbnail Cache')
        self.clear_all_button.setToolTip(
            'Delete all cached thumbnails (will be regenerated on next use)')
        self.clear_all_button.setStyleSheet('QPushButton { color: #d32f2f; }')  # Red text for destructive action
        self.clear_all_button.clicked.connect(self.clear_all_thumbnail_cache)

        # Size label and calculate button for all cache
        self.clear_all_size_label = QLabel('(click to calculate)')
        self.clear_all_size_label.setStyleSheet('color: #666; font-size: 10px; margin-left: 10px;')

        self.calc_all_size_button = QPushButton('Calculate')
        self.calc_all_size_button.setToolTip('Calculate total thumbnail cache size')
        self.calc_all_size_button.clicked.connect(self._calculate_all_cache_size)

        # All cache row (button + size + calc)
        all_row_layout = QHBoxLayout()
        all_row_layout.setSpacing(10)
        all_row_layout.addWidget(self.clear_all_button)
        all_row_layout.addWidget(self.clear_all_size_label)
        all_row_layout.addWidget(self.calc_all_size_button)
        all_row_layout.addStretch()

        # Clear all databases button
        self.clear_all_db_button = QPushButton('Clear All Image Index Databases')
        self.clear_all_db_button.setToolTip(
            'Delete all .taggui_index.db files from all previously opened directories. '
            'Use this if databases are corrupted or to free disk space.')
        self.clear_all_db_button.setStyleSheet('QPushButton { color: #d32f2f; }')  # Red text
        self.clear_all_db_button.clicked.connect(self.clear_all_databases)

        # Size label and calculate button for all databases
        self.clear_all_db_size_label = QLabel('(click to calculate)')
        self.clear_all_db_size_label.setStyleSheet('color: #666; font-size: 10px; margin-left: 10px;')

        self.calc_all_db_size_button = QPushButton('Calculate')
        self.calc_all_db_size_button.setToolTip('Calculate total database size')
        self.calc_all_db_size_button.clicked.connect(self._calculate_all_db_size)

        # All databases row (button + size + calc)
        all_db_row_layout = QHBoxLayout()
        all_db_row_layout.setSpacing(10)
        all_db_row_layout.addWidget(self.clear_all_db_button)
        all_db_row_layout.addWidget(self.clear_all_db_size_label)
        all_db_row_layout.addWidget(self.calc_all_db_size_button)
        all_db_row_layout.addStretch()

        # Make all clear buttons the same width (use the wider one)
        max_width = max(self.clear_current_button.sizeHint().width(),
                       self.clear_all_button.sizeHint().width(),
                       self.clear_all_db_button.sizeHint().width())
        button_width = int(max_width * 1.1)
        self.clear_current_button.setFixedWidth(button_width)
        self.clear_all_button.setFixedWidth(button_width)
        self.clear_all_db_button.setFixedWidth(button_width)

        # Make all calculate buttons compact and same width
        calc_button_width = self.calc_current_size_button.sizeHint().width()
        self.calc_current_size_button.setFixedWidth(calc_button_width)
        self.calc_all_size_button.setFixedWidth(calc_button_width)
        self.calc_all_db_size_button.setFixedWidth(calc_button_width)

        cache_buttons_layout.addLayout(current_row_layout)
        cache_buttons_layout.addSpacing(10)
        cache_buttons_layout.addLayout(all_row_layout)
        cache_buttons_layout.addSpacing(10)
        cache_buttons_layout.addLayout(all_db_row_layout)

        grid_layout.addLayout(cache_buttons_layout, 5, 1,
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

        # Masonry/List auto-switch threshold
        grid_layout.addWidget(QLabel('Keep masonry until (thumbnail px)'), 1, 0,
                              Qt.AlignmentFlag.AlignRight)
        masonry_switch_threshold_spin_box = SettingsSpinBox(
            key='masonry_list_switch_threshold',
            minimum=64, maximum=1024, default=150)
        masonry_switch_threshold_spin_box.setToolTip(
            'Auto-switches to List mode when thumbnail size reaches this value.\n'
            'Higher value = masonry allowed for larger thumbnails.\n'
            'Set above 512 to effectively disable auto-switch.\n'
            'Applied live.')
        grid_layout.addWidget(masonry_switch_threshold_spin_box, 1, 1,
                              Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(grid_layout)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    def _get_cache_size(self, directory: Path) -> str:
        """
        Calculate total cache size in human-readable format.

        Args:
            directory: Directory to calculate size for

        Returns:
            Human-readable size string (e.g., "234 MB")
        """
        if not directory.exists():
            return "0 B"

        try:
            total_size = 0
            for file_path in directory.rglob('*'):
                if file_path.is_file():
                    total_size += file_path.stat().st_size

            # Convert to human-readable format
            for unit in ['B', 'KB', 'MB', 'GB']:
                if total_size < 1024:
                    return f"{total_size:.1f} {unit}" if total_size > 0 else f"{int(total_size)} {unit}"
                total_size /= 1024

            return f"{total_size:.1f} TB"
        except Exception:
            return "? (error)"

    @Slot()
    def _calculate_current_directory_size(self):
        """Calculate cache size for current directory."""
        self.clear_current_size_label.setText('Calculating...')
        self.calc_current_size_button.setEnabled(False)

        from PySide6.QtCore import QTimer

        def do_calculation():
            thumbnail_cache = get_thumbnail_cache()
            current_dir = None
            if settings.contains('directory_path'):
                directory_path_str = settings.value('directory_path', type=str)
                if directory_path_str:
                    current_dir = Path(directory_path_str)

            if not current_dir or not current_dir.exists():
                self.clear_current_size_label.setText('(no directory loaded)')
                self.calc_current_size_button.setEnabled(True)
                return

            if not thumbnail_cache.enabled or not thumbnail_cache.cache_dir.exists():
                self.clear_current_size_label.setText('(empty)')
                self.calc_current_size_button.setEnabled(True)
                return

            try:
                from models.image_list_model import get_file_paths
                image_suffixes_string = settings.value(
                    'image_list_file_formats',
                    defaultValue=DEFAULT_SETTINGS['image_list_file_formats'], type=str)
                image_suffixes = []
                for suffix in image_suffixes_string.split(','):
                    suffix = suffix.strip().lower()
                    if not suffix.startswith('.'):
                        suffix = '.' + suffix
                    image_suffixes.append(suffix)

                file_paths = get_file_paths(current_dir)
                image_paths = [path for path in file_paths if path.suffix.lower() in image_suffixes]

                dir_cache_size = 0
                for image_path in image_paths:
                    try:
                        mtime = image_path.stat().st_mtime
                        cache_key = thumbnail_cache._get_cache_key(image_path, mtime, 512)
                        cache_path = thumbnail_cache._get_cache_path(cache_key)
                        if cache_path.exists():
                            dir_cache_size += cache_path.stat().st_size
                    except Exception:
                        pass

                cache_size_str = self._format_size(dir_cache_size)
                self.clear_current_size_label.setText(cache_size_str)
            except Exception:
                self.clear_current_size_label.setText('(error)')
            finally:
                self.calc_current_size_button.setEnabled(True)

        # Run calculation after event loop returns to prevent blocking dialog open
        QTimer.singleShot(10, do_calculation)

    @Slot()
    def _calculate_all_cache_size(self):
        """Calculate total thumbnail cache size."""
        self.clear_all_size_label.setText('Calculating...')
        self.calc_all_size_button.setEnabled(False)

        from PySide6.QtCore import QTimer

        def do_calculation():
            thumbnail_cache = get_thumbnail_cache()

            if not thumbnail_cache.enabled or not thumbnail_cache.cache_dir.exists():
                self.clear_all_size_label.setText('(empty)')
                self.calc_all_size_button.setEnabled(True)
                return

            try:
                cache_size = self._get_cache_size(thumbnail_cache.cache_dir)
                self.clear_all_size_label.setText(cache_size)
            except Exception:
                self.clear_all_size_label.setText('(error)')
            finally:
                self.calc_all_size_button.setEnabled(True)

        QTimer.singleShot(10, do_calculation)

    @Slot()
    def _calculate_all_db_size(self):
        """Calculate total database size."""
        self.clear_all_db_size_label.setText('Calculating...')
        self.calc_all_db_size_button.setEnabled(False)

        from PySide6.QtCore import QTimer

        def do_calculation():
            try:
                recent_dirs = settings.value('recent_directories', [], type=list)
                total_db_size = 0
                db_count = 0

                for dir_path_str in recent_dirs:
                    db_path = Path(dir_path_str) / '.taggui_index.db'
                    if db_path.exists():
                        total_db_size += db_path.stat().st_size
                        db_count += 1

                if db_count > 0:
                    size_str = self._format_size(total_db_size)
                    self.clear_all_db_size_label.setText(f"{size_str} ({db_count} files)")
                else:
                    self.clear_all_db_size_label.setText('(no databases found)')
            except Exception:
                self.clear_all_db_size_label.setText('(error)')
            finally:
                self.calc_all_db_size_button.setEnabled(True)

        QTimer.singleShot(10, do_calculation)

    def _format_size(self, size: int) -> str:
        """Format byte size to human-readable string."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}" if size > 0 else f"{int(size)} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @Slot()
    def show_restart_warning(self):
        self.warning_label.setText(self.restart_warning)
        self.warning_label.show()

    @Slot(str)
    def _on_skin_changed(self, skin_name: str):
        """Handle video player skin change - applies immediately."""
        # Get main window and apply skin to video controls
        main_window = self.parent()
        if hasattr(main_window, 'video_controls'):
            video_controls = main_window.video_controls
            if hasattr(video_controls, 'switch_skin'):
                success = video_controls.switch_skin(skin_name)
                if success:
                    # Show success message in warning label temporarily
                    self.warning_label.setText(f'✓ Skin "{skin_name}" applied (no restart needed)')
                    self.warning_label.setStyleSheet('color: green;')
                    self.warning_label.show()
                    # Reset after 3 seconds
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(3000, self._reset_warning_label)
                else:
                    self.warning_label.setText(f'Failed to load skin: {skin_name}')
                    self.warning_label.setStyleSheet('color: red;')
                    self.warning_label.show()

    def _reset_warning_label(self):
        """Reset warning label to default state."""
        self.warning_label.hide()
        self.warning_label.setStyleSheet('color: red;')

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

    @Slot()
    def clear_current_directory_cache(self):
        """Clear cache for currently loaded directory only."""
        # Get current directory from settings
        current_dir = None
        if settings.contains('directory_path'):
            directory_path_str = settings.value('directory_path', type=str)
            if directory_path_str:
                current_dir = Path(directory_path_str)

        if not current_dir or not current_dir.exists():
            QMessageBox.warning(
                self,
                'No Directory Loaded',
                'No directory is currently loaded. Please load a directory first.'
            )
            return

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            'Confirm Clear Current Directory Cache',
            f'This will delete:\n\n'
            f'• Dimension cache (.taggui_index.db)\n'
            f'• All thumbnails for images in:\n'
            f'  {current_dir}\n\n'
            f'Cache will be rebuilt when you reload this directory.\n\n'
            f'Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted_count = 0

            # Close database connection before deleting (avoid WinError 32)
            try:
                main_window = self.parent()
                if hasattr(main_window, 'image_list_model'):
                    image_list_model = main_window.image_list_model
                    if hasattr(image_list_model, '_db') and image_list_model._db:
                        image_list_model._db.close()
                        print("[CACHE] Closed database connection before deletion")
            except Exception as e:
                print(f"[CACHE] Warning: couldn't close DB connection: {e}")

            # Delete dimension cache database
            db_path = current_dir / '.taggui_index.db'
            if db_path.exists():
                db_path.unlink()
                deleted_count += 1

            # Delete thumbnails for this directory
            # We need to delete cached thumbnails that match files in this directory
            thumbnail_cache = get_thumbnail_cache()
            if thumbnail_cache.enabled and thumbnail_cache.cache_dir.exists():
                # Get all image files in current directory
                from models.image_list_model import get_file_paths
                image_suffixes_string = settings.value(
                    'image_list_file_formats',
                    defaultValue=DEFAULT_SETTINGS['image_list_file_formats'], type=str)
                image_suffixes = []
                for suffix in image_suffixes_string.split(','):
                    suffix = suffix.strip().lower()
                    if not suffix.startswith('.'):
                        suffix = '.' + suffix
                    image_suffixes.append(suffix)

                file_paths = get_file_paths(current_dir)
                image_paths = [path for path in file_paths if path.suffix.lower() in image_suffixes]

                # Delete cache for each image
                for image_path in image_paths:
                    try:
                        mtime = image_path.stat().st_mtime
                        cache_key = thumbnail_cache._get_cache_key(
                            image_path, mtime, 512  # Default thumbnail size
                        )
                        cache_path = thumbnail_cache._get_cache_path(cache_key)
                        if cache_path.exists():
                            cache_path.unlink()
                            deleted_count += 1
                    except Exception:
                        pass  # Skip files that fail

            QMessageBox.information(
                self,
                'Cache Cleared',
                f'Successfully cleared cache for current directory.\n'
                f'Deleted {deleted_count} cache files.\n\n'
                f'Reloading directory...'
            )

            # Reset size label
            self.clear_current_size_label.setText('(cleared - click to recalculate)')

            # Reload directory to rebuild cache
            try:
                main_window = self.parent()
                if hasattr(main_window, 'image_list_model'):
                    # Close dialog first so user sees the reload happening
                    self.accept()
                    main_window.image_list_model.load_directory(current_dir)
            except Exception as e:
                print(f"[CACHE] Warning: couldn't reload directory: {e}")

        except Exception as e:
            QMessageBox.critical(
                self,
                'Error',
                f'Failed to clear cache: {str(e)}'
            )

    @Slot()
    def clear_all_thumbnail_cache(self):
        """Clear all thumbnail cache."""
        thumbnail_cache = get_thumbnail_cache()

        if not thumbnail_cache.enabled:
            QMessageBox.information(
                self,
                'Cache Disabled',
                'Thumbnail cache is currently disabled in settings.'
            )
            return

        if not thumbnail_cache.cache_dir.exists():
            QMessageBox.information(
                self,
                'Cache Empty',
                'Thumbnail cache directory does not exist or is already empty.'
            )
            return

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            'Confirm Clear All Thumbnail Cache',
            f'This will permanently delete ALL cached thumbnails from:\n'
            f'{thumbnail_cache.cache_dir}\n\n'
            f'Thumbnails will be regenerated when needed.\n\n'
            f'Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted_count = 0

            # Delete all cache files
            for cache_file in thumbnail_cache.cache_dir.rglob('*.webp'):
                try:
                    cache_file.unlink()
                    deleted_count += 1
                except Exception:
                    pass

            # Also delete old PNG files if any remain
            for cache_file in thumbnail_cache.cache_dir.rglob('*.png'):
                try:
                    cache_file.unlink()
                    deleted_count += 1
                except Exception:
                    pass

            QMessageBox.information(
                self,
                'Cache Cleared',
                f'Successfully cleared all thumbnail cache.\n'
                f'Deleted {deleted_count} cached thumbnails.'
            )
            # Reset size label instead of recalculating
            self.clear_all_size_label.setText('(cleared - click to recalculate)')

        except Exception as e:
            QMessageBox.critical(
                self,
                'Error',
                f'Failed to clear cache: {str(e)}'
            )

    @Slot()
    def clear_all_databases(self):
        """Clear all .taggui_index.db files from all recent directories."""
        # Get list of recent directories
        recent_dirs = settings.value('recent_directories', [], type=list)

        if not recent_dirs:
            QMessageBox.information(
                self,
                'No Databases Found',
                'No image index databases found in recent directories.'
            )
            return

        # Find all database files
        db_files = []
        for dir_path_str in recent_dirs:
            db_path = Path(dir_path_str) / '.taggui_index.db'
            if db_path.exists():
                db_files.append(db_path)

        if not db_files:
            QMessageBox.information(
                self,
                'No Databases Found',
                'No .taggui_index.db files found in recent directories.'
            )
            return

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            'Confirm Clear All Image Index Databases',
            f'This will permanently delete {len(db_files)} database file(s):\n\n'
            f'{chr(10).join([f"• {db.parent.name}/.taggui_index.db" for db in db_files[:5]])}'
            f'{f"{chr(10)}...and {len(db_files) - 5} more" if len(db_files) > 5 else ""}\n\n'
            f'Databases will be rebuilt when you open these directories.\n\n'
            f'Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted_count = 0
            failed_count = 0

            for db_path in db_files:
                try:
                    db_path.unlink()
                    deleted_count += 1
                except Exception:
                    failed_count += 1

            message = f'Successfully deleted {deleted_count} database file(s).'
            if failed_count > 0:
                message += f'\n{failed_count} file(s) could not be deleted (may be in use).'

            QMessageBox.information(
                self,
                'Databases Cleared',
                message
            )
            # Reset size label instead of recalculating
            self.clear_all_db_size_label.setText('(cleared - click to recalculate)')

        except Exception as e:
            QMessageBox.critical(
                self,
                'Error',
                f'Failed to clear databases: {str(e)}'
            )
