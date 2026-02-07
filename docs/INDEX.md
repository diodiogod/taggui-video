# TagGUI Project Index

TagGUI is a desktop app for image/video tagging, captioning, and dataset preparation with paginated masonry support in active development.

## Root Files
- `AGENTS.md`: Active Codex project instructions and rules.
- `README.md`: User-facing project documentation.
- `PLAN.md`: Current 1M+ paginated masonry implementation plan.
- `PLANS/1M_images_architecture.md`: Additional architecture notes for large datasets.
- `requirements.txt`: Python dependencies.
- `run_taggui.py`: Root launcher script.
- `start_windows.bat`: Windows startup/bootstrap script.
- `start_linux.sh`: Linux startup/bootstrap script.
- `taggui-linux.spec`: Linux build spec.
- `taggui-windows.spec`: Windows build spec.
- `LICENSE`: Project license.

## Active Docs (`docs/`)
- `docs/INDEX.md`: This index.
- `docs/DISABLED_FEATURES.md`: Features intentionally disabled/removed.
- `docs/MASONRY_WINDOWED_STRICT_HANDOFF.md`: Current masonry strict-mode handoff and known hurdles.
- `docs/MASONRY_CURRENT_PROBLEMS_MATRIX.md`: Repro matrix and current fail/pass status.

## Archived Docs (`docs/archive/`)
- `docs/archive/BUFFERED_MASONRY_STATUS.md`: Older status report from earlier buffered masonry phase.
- `docs/archive/CLAUDE.md`: Legacy AI-agent instruction set (archived).
- `docs/archive/GEMINI.md`: Legacy AI-agent instruction set (archived).
- `docs/archive/PROJECT_INDEX.md`: Previous project index (replaced by this file).

## Main Package (`taggui/`)
- `taggui/run_gui.py`: Main GUI entry point.

### Models (`taggui/models/`)
- `image_list_model.py`: Core paginated image model, page loading, sorting, and DB-backed data access.
- `proxy_image_list_model.py`: Filter/sort proxy and view-facing transformations.
- `paginated_image_model.py`: Pagination-focused model helpers.
- `image_tag_list_model.py`: Tag list model for selected image context.
- `tag_counter_model.py`: Tag counting model.
- `proxy_tag_counter_model.py`: Proxy for tag count filtering/sorting.

### Widgets (`taggui/widgets/`)
- `main_window.py`: Main application window and top-level orchestration.
- `image_list.py`: List/masonry rendering, scroll ownership, strict windowed behavior.
- `image_viewer.py`: Main image/video preview viewer.
- `image_tags_editor.py`: Tag editing panel for current media.
- `all_tags_editor.py`: Bulk/all-tags editor.
- `auto_captioner.py`: Auto-caption UI integration.
- `auto_markings.py`: Auto-marking UI integration.
- `marking_view.py`: Marking canvas integration.
- `masonry_layout.py`: Masonry layout computation logic.
- `masonry_worker.py`: Background masonry worker/executor integration.
- `video_player.py`: Video playback UI.
- `video_controls.py`: Video playback/edit controls.
- `descriptive_text_edit.py`: Enhanced text edit control.
- `field_history_popup.py`: Input history popup UI.
- `marking/marking_item.py`: Marking graphics item.
- `marking/marking_label.py`: Marking label item.
- `marking/resize_hint_hud.py`: Resize HUD overlay for markings.

### Dialogs (`taggui/dialogs/`)
- `settings_dialog.py`: App settings UI.
- `export_dialog.py`: Export workflow dialog.
- `caption_multiple_images_dialog.py`: Batch caption dialog.
- `batch_reorder_tags_dialog.py`: Batch tag reorder dialog.
- `find_and_replace_dialog.py`: Find/replace tags dialog.
- `prompt_history_dialog.py`: Prompt history dialog.

### Controllers (`taggui/controllers/`)
- `menu_manager.py`: Main menu wiring.
- `toolbar_manager.py`: Toolbar wiring.
- `signal_manager.py`: Signal/slot wiring.
- `video_editing_controller.py`: Video editing workflow control.

### Utilities (`taggui/utils/`)
- `settings.py`: Persistent settings access.
- `image_index_db.py`: DB index/cache layer for large datasets.
- `thumbnail_cache.py`: Thumbnail cache management.
- `image.py`: Image/media utility helpers.
- `utils.py`: General utility helpers.
- `video_editor.py`: Legacy video editor bridge module.
- `video/video_editor.py`: Current video editor implementation.
- `video/batch_processor.py`: Batch video operations.
- `video/frame_editor.py`: Frame editing operations.
- `video/sar_fixer.py`: Sample aspect ratio fixes.
- `video/validator.py`: Video validation helpers.
- `video/common.py`: Shared video utility functions.
- `icons.py`: Icon loading helpers.
- `grid.py`: Grid helpers.
- `crop_applier.py`: Crop application utilities.
- `target_dimension.py`: Dimension target helpers.
- `prompt_history.py`: Prompt history persistence.
- `field_history.py`: Field history persistence.
- `focused_scroll_mixin.py`: Focused scrolling behavior.
- `key_press_forwarder.py`: Key-forwarding utilities.
- `text_edit_item_delegate.py`: Qt item delegate for text editing.
- `spell_highlighter.py`: Spell highlighting.
- `grammar_checker.py`: Grammar checking integration.
- `settings_widgets.py`: Shared settings UI widgets.
- `big_widgets.py`: Large composite widgets.
- `ModelThread.py`: Model execution thread helpers.
- `enums.py`: Shared enums.
- `jxlutil.py`: JPEG XL utilities.
- `rect.py`: Rectangle helpers.
- `shortcut_remover.py`: Shortcut cleanup utilities.

### Auto Captioning (`taggui/auto_captioning/`)
- `auto_captioning_model.py`: Base captioning model interface.
- `captioning_thread.py`: Caption generation threading.
- `models_list.py`: Caption model registry.
- `models/*.py`: Individual model adapters (CogVLM, Florence, LLaVA variants, WD tagger, etc.).

### Auto Marking (`taggui/auto_marking/`)
- `marking_thread.py`: Background auto-marking thread.
