# Skin Property Reference

Complete list of all properties you can customize in video player skins.

## How to Use This Reference

**In Designer:** Hover over any control to see its property name and YAML path.

**Communicating Changes:** Use these exact property names when requesting modifications.
Example: "Claude, make `button_size` adjustable from 20-80 instead of 24-60"

---

## Layout Properties

| Property Name | YAML Path | Description | Range/Type |
|--------------|-----------|-------------|------------|
| `control_bar_height` | `video_player.layout.control_bar_height` | Height of entire control bar | 40-100 px |
| `control_bar_position` | `video_player.layout.control_bar_position` | Position of controls | "top", "bottom", "overlay" |
| `button_alignment` | `video_player.layout.button_alignment` | How buttons align horizontally | "left", "center", "right" |
| `timeline_position` | `video_player.layout.timeline_position` | Timeline slider position | "above", "below", "integrated" |
| `button_spacing` | `video_player.layout.button_spacing` | Gap between adjacent buttons | 4-24 px |
| `section_spacing` | `video_player.layout.section_spacing` | Gap between major sections | 4-40 px |

---

## Button Properties

| Property Name | YAML Path | Description | Range/Type |
|--------------|-----------|-------------|------------|
| `button_size` | `video_player.styling.button_size` | Width & height of buttons | 24-60 px |
| `button_icon_color` | `video_player.styling.button_icon_color` | Color of button icons/text | Hex color |
| `button_bg_color` | `video_player.styling.button_bg_color` | Default button background | Hex color |
| `button_hover_color` | `video_player.styling.button_hover_color` | Background on hover | Hex color |
| `button_border` | `video_player.styling.button_border` | Border style | CSS border string |
| `button_border_radius` | `video_player.styling.button_border_radius` | Corner roundness | 0-20 px |

---

## Slider Properties

| Property Name | YAML Path | Description | Range/Type |
|--------------|-----------|-------------|------------|
| `timeline_height` | `video_player.styling.timeline_height` | Thickness of timeline slider | 4-20 px |
| `timeline_color` | `video_player.styling.timeline_color` | Progress fill color | Hex color |
| `timeline_bg_color` | `video_player.styling.timeline_bg_color` | Unfilled background | Hex color |
| `slider_handle_size` | `video_player.styling.slider_handle_size` | Width of slider handle | 12-24 px |
| `slider_handle_color` | `video_player.styling.slider_handle_color` | Handle fill color | Hex color |
| `slider_handle_border` | `video_player.styling.slider_handle_border` | Handle border | CSS border string |

---

## Loop Marker Properties

| Property Name | YAML Path | Description | Range/Type |
|--------------|-----------|-------------|------------|
| `loop_marker_start_color` | `video_player.styling.loop_marker_start_color` | Start triangle color | Hex color |
| `loop_marker_end_color` | `video_player.styling.loop_marker_end_color` | End triangle color | Hex color |
| `loop_marker_outline` | `video_player.styling.loop_marker_outline` | Marker outline color | Hex color |
| `loop_marker_outline_width` | `video_player.styling.loop_marker_outline_width` | Outline thickness | 1-4 px |

---

## Speed Slider Gradient

| Property Name | YAML Path | Description | Range/Type |
|--------------|-----------|-------------|------------|
| `speed_gradient_start` | `video_player.styling.speed_gradient_start` | Left gradient color (slow) | Hex color |
| `speed_gradient_mid` | `video_player.styling.speed_gradient_mid` | Middle gradient color | Hex color |
| `speed_gradient_end` | `video_player.styling.speed_gradient_end` | Right gradient color (fast) | Hex color |

---

## General Colors

| Property Name | YAML Path | Description | Range/Type |
|--------------|-----------|-------------|------------|
| `background` | `video_player.styling.background` | Background behind controls | Hex color |
| `control_bar_color` | `video_player.styling.control_bar_color` | Main control bar background | Hex color |
| `control_bar_opacity` | `video_player.styling.control_bar_opacity` | Transparency level | 0.0-1.0 |
| `text_color` | `video_player.styling.text_color` | Primary text color | Hex color |
| `text_secondary_color` | `video_player.styling.text_secondary_color` | Secondary/dimmed text | Hex color |
| `label_font_size` | `video_player.styling.label_font_size` | Text size in labels | 8-16 px |

---

## Borders

| Property Name | YAML Path | Description | Range/Type |
|--------------|-----------|-------------|------------|
| `radius` | `video_player.borders.radius` | Global border radius | 0-20 px |
| `control_bar_border` | `video_player.borders.control_bar_border` | Control bar border | CSS border string |
| `button_border` | `video_player.borders.button_border` | Button border override | CSS border string |

---

## Shadows

| Property Name | YAML Path | Description | Range/Type |
|--------------|-----------|-------------|------------|
| `control_bar` | `video_player.shadows.control_bar` | Control bar shadow | CSS shadow string |
| `button` | `video_player.shadows.button` | Individual button shadows | CSS shadow string |
| `overlay` | `video_player.shadows.overlay` | Overlay shadows | CSS shadow string |

---

## Token System

Tokens let you define values once and reuse them. Reference with `{tokens.path.to.value}`.

### Example:
```yaml
tokens:
  colors:
    primary: "#2196F3"

video_player:
  styling:
    timeline_color: "{tokens.colors.primary}"
    button_hover_color: "{tokens.colors.primary}"
```

---

## Requesting Changes

**Good requests:**
- "Make `button_size` range 20-80 instead of 24-60"
- "Add control for `control_bar_opacity` in the designer"
- "Change default `timeline_color` to blue"

**Even better:**
- "Add slider for `speed_gradient_start` in the Speed Slider section"
- "Make `loop_marker_start_color` editable in Colors panel"

---

## Currently in Designer

✅ control_bar_height
✅ section_spacing
✅ button_size
✅ button_spacing
✅ button_border_radius
✅ button_bg_color
✅ button_hover_color
✅ timeline_height
✅ timeline_color
✅ background
✅ control_bar_color
✅ loop_marker_start_color
✅ loop_marker_end_color

**Not yet in designer (can be added):**
- Speed gradient colors
- Slider handle properties
- Text colors/sizes
- Shadows
- Advanced border controls
- Opacity controls

Request any of these and they'll be added!
