# Video Player Skin System

## Overview

The video player skin system provides visual customization and interactive positioning for video control widgets. Users can edit skins via an interactive designer with live preview.

## Architecture

```
┌─────────────────────────────────────────┐
│ Interactive Designer (QGraphicsScene)   │
│ - Visual mockup                         │
│ - Drag/drop positioning                 │
│ - Color/opacity pickers                 │
└──────────────┬──────────────────────────┘
               │ Saves to
               ▼
┌─────────────────────────────────────────┐
│ YAML Skin Files                         │
│ - styling: colors, sizes, opacity       │
│ - layout: spacing, alignment            │
│ - designer_positions: custom offsets    │
└──────────────┬──────────────────────────┘
               │ Loaded by
               ▼
┌─────────────────────────────────────────┐
│ SkinManager → SkinApplier               │
│ - Loads/switches skins                  │
│ - Applies to Qt widgets                 │
└──────────────┬──────────────────────────┘
               │ Applied to
               ▼
┌─────────────────────────────────────────┐
│ VideoControlsWidget                     │
│ - 3-row layout (controls/timeline/info) │
│ - Position offset system                │
└─────────────────────────────────────────┘
```

## Key Files

### `taggui/skins/engine/skin_applier.py`
**Responsibility**: Applies skin properties to Qt widgets

**Key methods**:
- `apply_to_control_bar(control_bar)` - Background color/opacity
- `apply_to_button(button)` - Button styling
- `apply_to_timeline_slider(slider)` - Timeline appearance
- `apply_to_speed_slider(slider)` - Speed gradient
- `apply_to_label(label)` - Text styling

**Background transparency**:
```python
# Uses QPalette + QColor.setAlphaF() (not stylesheet rgba)
bg_qcolor = QColor(bg_color)
bg_qcolor.setAlphaF(opacity)  # 0.0 - 1.0
palette.setColor(QPalette.ColorRole.Window, bg_qcolor)
control_bar.setPalette(palette)
```

### `taggui/widgets/video_controls.py`
**Responsibility**: Video player controls with skin support

**Key methods**:
- `apply_current_skin()` - Applies active skin to all widgets
- `apply_designer_positions()` - Applies custom position offsets
- `_apply_designer_positions_now()` - Internal position application

**Layout structure**:
- Row 1: Play/stop/mute, navigation, frame controls, speed slider
- Row 2: Timeline slider with loop markers
- Row 3: Time/FPS/frame labels, loop controls

### `taggui/dialogs/skin_designer_interactive.py`
**Responsibility**: Interactive visual skin editor

**Key methods**:
- `_build_realistic_mockup()` - Creates visual mockup matching real player
- `update_element_color()` - Handles color changes
- `update_element_position()` - Tracks position changes
- `update_element_font()` - Manages font customization

## Position Offset System (Option C: Hybrid)

**Concept**: Layouts provide base positioning, designer offsets override individual widgets.

**Flow**:
1. User drags widget in designer → saves to `designer_positions` dict
2. Skin loaded → `apply_designer_positions()` called
3. 50ms delay (lets layout settle) → `_apply_designer_positions_now()`
4. `widget.setGeometry(x, y, w, h)` forces absolute position
5. On resize → reapply positions (prevents layout override)

**Widget mapping**:
```python
widget_map = {
    'play_button': self.play_pause_btn,
    'stop_button': self.stop_btn,
    # ... etc
}
```

**Storage format** (YAML):
```yaml
designer_positions:
  play_button:
    x: 150
    y: 10
  stop_button:
    x: 250
    y: 10
```

## Per-Element Customization

Each widget can have individual properties using `{property_name}_{attribute}` pattern:

```yaml
styling:
  # Global defaults
  button_bg_color: '#2b2b2b'
  button_size: 40

  # Per-button overrides
  play_button_color: '#FF0000'
  play_button_opacity: 0.8
  stop_button_color: '#00FF00'

  # Per-label fonts
  time_label_font_family: 'Courier New'
  time_label_font_size: 14
  time_label_font_weight: 'bold'
```

## Common Issues & Solutions

### Background Transparency Not Working
**Symptom**: Background fully transparent or fully opaque
**Cause**: Using stylesheet rgba() (Qt doesn't support it properly)
**Solution**: Use QPalette + QColor.setAlphaF() instead

### Position Offsets Not Applying
**Symptom**: Widgets snap back to layout positions
**Cause**: Layout manager overriding positions on resize
**Solution**: Reapply positions in resizeEvent via QTimer

### Designer Mockup Doesn't Match Player
**Symptom**: Designer shows different layout than real player
**Cause**: Hardcoded mockup positions vs dynamic layout
**Solution**: Build mockup using same structure as video_controls.py 3-row layout

### setWindowOpacity Makes Everything Transparent
**Symptom**: Buttons become transparent along with background
**Cause**: setWindowOpacity affects entire widget tree
**Solution**: Never use setWindowOpacity, use QPalette alpha instead

## Extension Points

### Adding New Widgets to Designer
1. Add widget to `_build_realistic_mockup()` with property_name
2. Add to `widget_map` in `apply_designer_positions()`
3. Add skin properties to YAML (color, opacity, font)

### Adding New Skin Properties
1. Add property to skin YAML under `styling` or `layout`
2. Read in `SkinApplier.__init__()`: `self.styling.get('new_property', default)`
3. Apply in relevant `apply_to_*()` method

### Custom Positioning Logic
Override `_apply_designer_positions_now()` to implement:
- Relative positioning (% of parent)
- Snap-to-grid
- Constraint-based layout
- Animation/transitions

## Technical Constraints

- **QGraphicsScene** (designer) uses absolute positioning
- **QLayout** (real player) uses automatic positioning
- Hybrid approach: layout first, then override with setGeometry()
- Position offsets are in absolute pixels (not scaled)
- Reapplication on resize maintains custom positions

## Testing

Run visual tests:
```bash
python test_complete_fixes.py  # Background transparency + positions
```

Check transparency:
```python
palette = widget.palette()
bg_color = palette.color(widget.backgroundRole())
assert 0 < bg_color.alpha() < 255  # Semi-transparent
```

Check positions:
```python
assert widget.pos().x() == expected_x
assert widget.pos().y() == expected_y
```
