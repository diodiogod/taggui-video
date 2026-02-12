# TagGUI Project Index

TagGUI is a cross-platform desktop app for tagging images and captions for AI datasets, with video editing features and customizable UI.

**Latest Features:**
- Windowed strict masonry for 1M+ image datasets
- Incremental masonry caching for smooth scrolling
- **NEW: Interactive skin designer for video player** (drag-and-drop visual editor)

---

## Root Files

- `CLAUDE.md`: Instructions for Claude AI usage
- `INSTRUCTION.md`: Project development instructions
- `SKIN_SYSTEM.md`: Technical overview of video player skin system
- `start_windows.bat`: Windows startup script with venv activation
- `start_linux.sh`: Linux startup script with venv activation
- `requirements.txt`: Python dependencies (includes PyYAML for skin system)
- `taggui/run_gui.py`: Main entry point

---

## Main Package (taggui/taggui/)

### Controllers (controllers/)
- `video_editing_controller.py`: Video editing operations (extract, remove, repeat, fix frame count, SAR fix)
- `toolbar_manager.py`: Toolbar creation and management
- `menu_manager.py`: Menu bar creation and management
- `signal_manager.py`: Signal connection management

### Auto Captioning (auto_captioning/)
- `auto_captioning_model.py`: Base class for captioning models
- `captioning_thread.py`: Background thread for captioning tasks
- `models_list.py`: Registry of available captioning models
- `models/*.py`: Model implementations (CogVLM, Florence-2, JoyCaption, LLaVA, etc.)

### Dialogs (dialogs/)
- `batch_reorder_tags_dialog.py`: Dialog for batch tag reordering
- `caption_multiple_images_dialog.py`: Dialog for batch captioning
- `export_dialog.py`: Export settings dialog
- `find_and_replace_dialog.py`: Find/replace tags dialog
- `prompt_history_dialog.py`: Prompt history browser with search
- `settings_dialog.py`: Application settings dialog with skin selector
- **`skin_designer_interactive.py`: Interactive visual skin designer (drag, resize, color pick)**
- `skin_designer_visual.py`: Alternative visual designer (deprecated)
- `skin_designer_dialog.py`: Original list-based designer (deprecated)

### Models (models/)
- `image_list_model.py`: Core paginated data model (parallel loading, cache saving)
- `image_tag_list_model.py`: Data model for image tags
- `proxy_image_list_model.py`: Proxy model for filtered image list
- `proxy_tag_counter_model.py`: Proxy model for tag counting
- `tag_counter_model.py`: Model for tag statistics

### Utils (utils/)
- `image.py`: Image processing utilities (QImage dataclass, lazy QPixmap)
- `image_index_db.py`: SQLite-based image metadata database
- `thumbnail_cache.py`: Disk-based thumbnail cache with WebP compression
- `settings.py`: Application settings management
- `spell_highlighter.py`: Real-time spell checking
- `grammar_checker.py`: LanguageTool grammar checking
- `field_history.py`: Field history manager (100 entries per field)
- `prompt_history.py`: Prompt history with LRU ordering (10k max)

#### Video Utilities (utils/video/)
- `frame_editor.py`: Frame-level editing (extract, remove, repeat, N*4+1 fix)
- `sar_fixer.py`: SAR (Sample Aspect Ratio) fixing operations
- `batch_processor.py`: Batch video processing
- `video_editor.py`: Unified interface (backward compatibility wrapper)

### Widgets (widgets/)
- `image_list.py`: Main image list view with masonry layout (1472 lines)
- `image_viewer.py`: Image display and marking widget (605 lines)
- `image_tags_editor.py`: Image tags editor with descriptive mode
- `auto_captioner.py`: Auto-captioning widget with prompt/field history
- `descriptive_text_edit.py`: Text editor with spell/grammar checking
- **`video_controls.py`: Video playback controls with skin system integration (1900+ lines)**
- `video_player.py`: Hybrid video player (QMediaPlayer + OpenCV)
- `main_window.py`: Main application window (460 lines)
- `masonry_layout.py`: Masonry layout calculator with disk caching
- `masonry_worker.py`: Multiprocessing worker for non-blocking calculations

#### Marking Components (widgets/marking/)
- `marking_item.py`: Interactive marking rectangle with drag/resize
- `marking_label.py`: Editable text labels for markings
- `resize_hint_hud.py`: Visual crop hints/guides HUD

---

## Skin System (NEW)

### Structure
```
taggui/skins/
├── engine/              # Core skin system
│   ├── schema.py        # Property definitions and validation
│   ├── skin_loader.py   # YAML loading and token resolution
│   ├── skin_applier.py  # Applies skins to Qt widgets
│   └── skin_manager.py  # Orchestrates loading/switching
├── defaults/            # Built-in skins
│   ├── classic.yaml     # Original design (default)
│   ├── modern-dark.yaml # Sleek contemporary theme
│   ├── ocean.yaml       # Blue/teal theme
│   └── volcanic.yaml    # Green gradient theme
├── user/                # User-created skins
│   └── custom-example.yaml  # Template with documentation
├── README.md            # User guide for creating skins
└── PROPERTY_REFERENCE.md    # Complete property documentation
```

### Files

**Engine (skins/engine/)**
- `schema.py`: Defines all skinnable properties (colors, spacing, layout, etc.)
- `skin_loader.py`: Loads YAML, validates structure, resolves `{tokens.x.y}` references
- `skin_applier.py`: Applies skin styling to Qt widgets (buttons, sliders, labels)
- `skin_manager.py`: Lists available skins, loads/switches skins, manages state

**Default Skins (skins/defaults/)**
- `classic.yaml`: Exact original design (black, #2b2b2b buttons, 0.8 opacity)
- `modern-dark.yaml`: Contemporary design following `.interface-design/system.md`
- `ocean.yaml`: Blue/teal color scheme with oceanic gradient
- `volcanic.yaml`: Original green gradient (preserves existing look)

**User Skins (skins/user/)**
- `custom-example.yaml`: Fully documented template for creating custom skins

**Documentation**
- `README.md`: How to create/export/load skins, design principles, troubleshooting
- `PROPERTY_REFERENCE.md`: Complete list of all skinnable properties with YAML paths

### Features

**Interactive Designer**
- Drag elements to reposition
- Drag corners to resize
- Right-click for color picker (with opacity slider)
- Right-click labels for font picker
- Visual selection with glow effect
- Live preview on actual controls
- Export to YAML, load existing skins

**Skinnable Properties**
- Layout: control bar height, button spacing, section spacing
- Buttons: size, colors (default/hover), borders, radius
- Sliders: timeline height, colors, handle size/style
- Loop markers: start/end colors, outline
- Speed slider: 3-color gradient
- Text: colors, font sizes
- Opacity: control bar, elements
- Borders & shadows

**Access Points**
- Settings → General → "Video player skin" dropdown
- Right-click video controls → "🎨 Change Skin"
- Right-click video controls → "🎨 Design Custom Skin..."

---

## Design System

### `.interface-design/system.md`
Establishes TagGUI's design philosophy and tokens:
- **Direction:** "Speed with Style" - Modern, sleek dataset visualizer
- **Spacing scale:** 4/8/16/24/32 (no arbitrary values)
- **Color tokens:** Neutrals (OLED-like blacks), functional colors
- **Surface treatment:** Border radius, glass morphism hints, depth
- **Component patterns:** Buttons, sliders, control bars

All default skins follow this system for consistency.

---

## Memory System

### Auto Memory (`.claude/projects/.../memory/`)
- `MEMORY.md`: Persistent memory loaded into Claude's system prompt
- Tracks architecture decisions, key patterns, common issues
- User preferences for workflow and tools
- **Current Focus:** Windowed strict masonry, incremental caching, skin system

### Session Logs
- `*.jsonl`: Transcript logs for past context search (last resort)

---

## Key Architecture Patterns

### Windowed Strict Masonry
- Scrollbar = page selector, not pixel scroller
- Canonical domain controller: `_strict_canonical_domain_max()` is single source of truth
- Virtual average height only grows (prevents domain drift)
- Incremental caching: per-page masonry cache for smooth scrolling

### Skin System
- Declarative YAML files define all styling
- Token system: define values once, reference everywhere
- Separation: Schema → Loader → Applier → Manager
- Live switching: no restart needed, instant apply
- User-friendly: visual designer, no coding required

### Video Player
- Hybrid: QMediaPlayer (smooth playback) + OpenCV (frame-accurate seeking)
- Loop markers: draggable triangles above timeline
- Speed slider: rubberband effect with extended range (-12x to +12x)
- Skin integration: all styling controlled by skin system

---

## Recent Additions (Session 4)

### Skin System (Complete)
- Interactive visual designer with drag-and-drop
- Color picker with opacity slider
- Font picker for labels
- Resize handles on selected elements
- 4 default skins (Classic, Modern Dark, Ocean, Volcanic)
- Complete property reference documentation
- Live preview and export to YAML

### Fixes
- Classic skin: exact match to original hardcoded values
- Token resolution: prevents recursive processing bugs
- Opacity handling: proper type conversion
- Designer safety: lazy handle creation, error catching

---

## Dependencies

**Core:**
- PySide6==6.9.0
- pillow==11.2.1
- opencv-python==4.10.0.84
- PyYAML>=6.0 (for skin system)

**AI Models:**
- transformers==4.48.3
- torch (auto-installed by startup scripts)

**Utilities:**
- pyspellchecker==0.8.1
- language-tool-python>=2.10

---

## Testing

**Windows (venv):**
```bash
J:\Aitools\MyTagGUI\taggui_working\venv\Scripts\python.exe taggui\run_gui.py
```

**Linux (WSL):**
```bash
cd /mnt/j/Aitools/MyTagGUI/taggui_working
./start_linux.sh
```

**Skin Designer:**
1. Load video
2. Right-click controls → "🎨 Design Custom Skin..."
3. Drag elements, right-click for colors
4. Export to `skins/user/`

---

## Documentation Files

- `docs/INDEX.md`: This file
- `docs/FLOATING_VIEWERS_USER_GUIDE.md`: User guide for spawned/floating viewer behavior
- `docs/PLAN1_1M_images_architecture.md`: Original 1M images plan
- `docs/PLAN2_windowed_strict.md`: Windowed strict masonry design
- `docs/DISABLED_FEATURES.md`: Features temporarily disabled
- `docs/archive/`: Archived planning documents
- `SKIN_SYSTEM.md`: Technical skin system overview
- `taggui/skins/README.md`: User guide for skins
- `taggui/skins/PROPERTY_REFERENCE.md`: Complete property list

---

**Last Updated:** 2026-02-11 (Session 4 - Skin System Complete)
