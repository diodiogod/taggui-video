# Video Player Skin System

## Overview

TagGUI now has a complete, declarative skin system for the video player. Users can customize colors, spacing, layout, and styling WITHOUT writing code - just edit YAML files.

**Key Features:**
- ✅ **Live switching** - No restart needed, skins apply instantly
- ✅ **User-friendly** - Simple YAML format, no Python knowledge required
- ✅ **Extensible** - Users can create custom skins
- ✅ **Token system** - Define values once, reference everywhere
- ✅ **Dual UI** - Switch skins via Settings dialog OR right-click menu

---

## What Was Built

### 1. Skin Engine (`taggui/skins/engine/`)

**Core Components:**
- `schema.py` - Defines all skinnable properties (colors, spacing, layout, etc.)
- `skin_loader.py` - Loads & validates YAML skin files, resolves token references
- `skin_applier.py` - Applies skin styling to Qt widgets (buttons, sliders, labels)
- `skin_manager.py` - Orchestrates loading, switching, listing skins

**Architecture:**
```
User creates YAML → Loader validates → Applier applies to widgets → Instant update
```

### 2. Default Skins (`taggui/skins/defaults/`)

Three built-in skins:
1. **Modern Dark** - Sleek, contemporary design (following `.interface-design/system.md`)
2. **Ocean** - Blue/teal theme with oceanic gradients
3. **Volcanic** - Original green theme (preserves existing look)

### 3. User Skins (`taggui/skins/user/`)

- `custom-example.yaml` - Fully documented template for users to copy and modify
- Users drop `.yaml` files here, they appear in skin selector automatically

### 4. Integration

**video_controls.py:**
- Imports SkinManager
- Loads saved skin on startup (or default)
- `apply_current_skin()` - Applies skin to all widgets
- `switch_skin(name)` - Switches and applies new skin (live!)
- `contextMenuEvent()` - Right-click menu for skin selection
- `_open_skins_folder()` - Opens user skins folder in file explorer

**settings_dialog.py:**
- Added "Video player skin" dropdown in General tab
- Populates with available skins
- Live switching with success message
- No restart required!

**LoopSlider (video_controls.py):**
- Added `set_marker_colors()` to support skinned loop markers
- Uses instance color variables instead of hardcoded values

### 5. Design System (`.interface-design/system.md`)

Established TagGUI's design direction:
- **Philosophy:** "Speed with Style" - Modern, sleek visualizer
- **Spacing scale:** 4/8/16/24/32 (no arbitrary values)
- **Color tokens:** Neutrals, functional colors, semantic naming
- **Surface treatment:** Border radius, shadows, glass morphism
- **Component patterns:** Buttons, sliders, control bars

All default skins follow this system for consistency.

### 6. Documentation

- `taggui/skins/README.md` - Complete user guide for creating skins
- `user/custom-example.yaml` - Heavily commented example skin with all options
- `SKIN_SYSTEM.md` - This file (technical overview)

---

## How It Works

### For Users

1. **Browse skins:**
   - Settings → General → Video player skin dropdown
   - OR right-click video controls → Change Skin

2. **Create custom skin:**
   ```bash
   cd taggui/skins/user/
   cp custom-example.yaml my-skin.yaml
   # Edit my-skin.yaml
   ```

3. **Apply skin:**
   - Select from dropdown OR right-click menu
   - Changes apply **instantly** - no restart!

### For Developers

**Skin File Format (YAML):**
```yaml
name: "My Skin"
author: "Author Name"
version: "1.0"

tokens:
  colors:
    primary: "#FF00FF"
  spacing:
    sm: 8

video_player:
  layout:
    control_bar_height: 60
    button_spacing: "{tokens.spacing.sm}"

  styling:
    button_size: 32
    timeline_color: "{tokens.colors.primary}"
```

**Token Resolution:**
- `{tokens.colors.primary}` → Loader resolves to actual value
- Allows consistency across skin

**Live Switching Flow:**
```
User selects skin → switch_skin() called → Load YAML →
Create SkinApplier → Apply to widgets → Update UI → Done!
```

---

## What's Customizable

### Layout
- Control bar height, position (top/bottom/overlay)
- Button alignment (left/center/right)
- Spacing between buttons/sections
- Timeline position (above/below/integrated)

### Styling
- **Colors:** All UI elements (buttons, backgrounds, text, hover states)
- **Sizes:** Buttons, sliders, markers
- **Borders:** Radius, width, style
- **Shadows:** Depth effects for control bar, buttons, overlays
- **Gradients:** Speed slider 3-color gradient
- **Loop markers:** Start/end colors, outline

### Typography
- Label font sizes
- Text colors (primary, secondary)

---

## File Structure

```
taggui/
├── skins/
│   ├── engine/              # Skin system core
│   │   ├── __init__.py
│   │   ├── schema.py        # Property definitions
│   │   ├── skin_loader.py   # YAML loading
│   │   ├── skin_applier.py  # Qt widget styling
│   │   └── skin_manager.py  # Orchestration
│   ├── defaults/            # Built-in skins
│   │   ├── modern-dark.yaml
│   │   ├── ocean.yaml
│   │   └── volcanic.yaml
│   ├── user/                # User custom skins
│   │   └── custom-example.yaml
│   └── README.md
├── widgets/
│   └── video_controls.py    # Integrated with skin system
├── dialogs/
│   └── settings_dialog.py   # Skin selector in UI
└── .interface-design/
    └── system.md            # Design principles

requirements.txt             # Added PyYAML>=6.0
```

---

## Testing

To test the skin system:

1. **Start TagGUI:**
   ```bash
   python taggui/run_gui.py
   ```

2. **Open a video** to show video controls

3. **Switch skins:**
   - Settings → Video player skin → Select "Ocean"
   - OR right-click controls → Change Skin → Ocean
   - See instant update!

4. **Create custom skin:**
   - Copy `user/custom-example.yaml` to `user/my-skin.yaml`
   - Edit colors/spacing
   - Right-click controls → Change Skin → My Skin
   - See changes live!

---

## Technical Details

### Schema Validation

`SkinSchema.validate_structure()` checks:
- Required fields present (`name`, `version`)
- Valid enum values (control_bar_position, button_alignment, etc.)
- Returns `(valid: bool, error: str)` tuple

### Token Resolution Algorithm

```python
def _resolve_tokens(skin_data):
    # Find all {tokens.path.to.value} patterns
    # Navigate token hierarchy
    # Replace placeholders with actual values
    # Return resolved skin data
```

Recursive - handles tokens in nested structures.

### Widget Application

`SkinApplier` generates Qt stylesheets dynamically:
```python
def apply_to_button(button):
    stylesheet = f"""
        QPushButton {{
            background-color: {self.styling['button_bg_color']};
            ...
        }}
    """
    button.setStyleSheet(stylesheet)
```

Called for each widget type (buttons, sliders, labels, etc.)

---

## Future Enhancements

Potential additions:
- [ ] Skin preview thumbnails
- [ ] More layout positions (overlay controls)
- [ ] Animation speed customization
- [ ] Font family selection
- [ ] Hot-reload (watch YAML file changes)
- [ ] Skin marketplace/sharing platform
- [ ] Global app skins (beyond video player)

---

## Dependencies

Added to `requirements.txt`:
```
PyYAML>=6.0
```

No other new dependencies.

---

## Credits

Design System: `.interface-design/system.md` (inspired by https://github.com/Dammyjay93/interface-design)

**Philosophy:** "Speed with Style" - Modern, sleek dataset visualizer

Built for TagGUI video player customization.
