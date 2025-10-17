# TagGUI Project Index

TagGUI is a cross-platform desktop app for tagging images and captions for AI datasets, with video editing features.

## Root Files
- `CLAUDE.md`: Instructions for Claude AI usage
- `INSTRUCTION.md`: Project development instructions
- `taggui/.gitignore`: Git ignore patterns
- `taggui/LICENSE`: Project license
- `taggui/README.md`: Project documentation and features
- `taggui/requirements.txt`: Python dependencies
- `taggui/run_taggui.py`: Convenient launcher script for running from project root
- `taggui/taggui-linux.spec`: Linux build specification
- `taggui/taggui-windows.spec`: Windows build specification
- `taggui/VIDEO_EDITING_BUG_REPORT.md`: Video editing bug analysis

## Main Package (taggui/taggui/)
- `__init__.py`: Package initialization
- `run_gui.py`: Main GUI application entry point

### Auto Captioning (auto_captioning/)
- `__init__.py`: Subpackage init
- `auto_captioning_model.py`: Base class for captioning models
- `captioning_thread.py`: Background thread for captioning tasks
- `models_list.py`: Registry of available captioning models
- `models/__init__.py`: Models subpackage init
- `models/cogvlm.py`: CogVLM model implementation
- `models/cogvlm2.py`: CogVLM2 model implementation
- `models/florence_2.py`: Florence-2 model implementation
- `models/joycaption.py`: JoyCaption model implementation
- `models/kosmos_2.py`: Kosmos-2 model implementation
- `models/llava_1_point_5.py`: LLaVA 1.5 model implementation
- `models/llava_llama_3.py`: LLaVA Llama 3 model implementation
- `models/llava_next.py`: LLaVA Next model implementation
- `models/moondream.py`: Moondream model implementation
- `models/phi_3_vision.py`: Phi-3 Vision model implementation
- `models/wd_tagger.py`: WD Tagger model implementation
- `models/xcomposer2.py`: XComposer2 model implementation

### Auto Marking (auto_marking/)
- `marking_thread.py`: Background thread for automatic marking

### Dialogs (dialogs/)
- `__init__.py`: Dialogs subpackage init
- `batch_reorder_tags_dialog.py`: Dialog for batch tag reordering
- `caption_multiple_images_dialog.py`: Dialog for batch captioning
- `export_dialog.py`: Export settings dialog
- `find_and_replace_dialog.py`: Find/replace tags dialog
- `settings_dialog.py`: Application settings dialog

### Models (models/)
- `__init__.py`: Models subpackage init
- `image_list_model.py`: Data model for image list
- `image_tag_list_model.py`: Data model for image tags
- `proxy_image_list_model.py`: Proxy model for filtered image list
- `proxy_tag_counter_model.py`: Proxy model for tag counting
- `tag_counter_model.py`: Model for tag statistics

### Utils (utils/)
- `__init__.py`: Utils subpackage init
- `big_widgets.py`: Large UI widget components
- `enums.py`: Application enumerations
- `focused_scroll_mixin.py`: Scroll behavior mixin
- `grammar_checker.py`: LanguageTool grammar checking integration
- `grid.py`: Grid layout utilities
- `icons.py`: Icon management
- `image.py`: Image processing utilities
- `jxlutil.py`: JPEG XL format utilities
- `key_press_forwarder.py`: Keyboard event forwarding
- `ModelThread.py`: Thread for model operations
- `rect.py`: Rectangle utilities
- `settings_widgets.py`: Settings UI widgets
- `settings.py`: Application settings management
- `shortcut_remover.py`: Shortcut conflict resolution
- `spell_highlighter.py`: Real-time spell checking with pyspellchecker
- `target_dimension.py`: Dimension calculation utilities
- `text_edit_item_delegate.py`: Text editing delegate
- `utils.py`: General utility functions
- `video_editor.py`: Video editing operations

### Widgets (widgets/)
- `__init__.py`: Widgets subpackage init
- `all_tags_editor.py`: Widget for editing all tags
- `auto_captioner.py`: Auto-captioning widget
- `auto_markings.py`: Auto-marking widget
- `descriptive_text_edit.py`: Text editor with spell/grammar checking support
- `image_list.py`: Image list widget
- `image_tags_editor.py`: Image tags editor widget with descriptive mode
- `image_viewer.py`: Image display and marking widget
- `main_window.py`: Main application window
- `video_controls.py`: Video playback controls
- `video_player.py`: Video player widget

## Resources
- `clip-vit-base-patch32/`: CLIP tokenizer data files
- `images/`: Icons, screenshots, and UI assets