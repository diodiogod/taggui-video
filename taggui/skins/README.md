# TagGUI Video Player Skins

Customize the look and feel of your video player with declarative YAML skins!

## Quick Start

1. **Browse skins**: See available skins in `defaults/` folder
2. **Create your own**: Copy `user/custom-example.yaml` and modify it
3. **Live switching**: Skins apply instantly - no restart needed!

## Directory Structure

```
skins/
├── defaults/          # Built-in skins (don't edit these)
│   ├── modern-dark.yaml
│   ├── ocean.yaml
│   └── volcanic.yaml
├── user/              # Your custom skins go here!
│   └── custom-example.yaml
└── engine/            # Skin system code (don't touch)
```

## Creating Custom Skins

### Step 1: Copy the example

```bash
cp user/custom-example.yaml user/my-skin.yaml
```

### Step 2: Edit your skin

Open `user/my-skin.yaml` and customize:

```yaml
name: "My Awesome Skin"
author: "Your Name"
version: "1.0"

tokens:
  colors:
    primary: "#FF00FF"      # Change colors
    bg-primary: "#1A1A1A"

video_player:
  layout:
    control_bar_height: 70  # Adjust sizes
    button_spacing: 12

  styling:
    button_size: 36
    timeline_color: "{tokens.colors.primary}"  # Reference tokens!
```

### Step 3: Apply your skin

In TagGUI settings, select your skin from the dropdown. Changes apply **instantly**!

## What Can You Customize?

### Layout
- Control bar height, position (top/bottom/overlay)
- Button alignment (left/center/right)
- Spacing between elements
- Timeline position

### Colors
- All UI colors (buttons, backgrounds, text)
- Speed slider gradients
- Loop marker colors
- Hover/active states

### Styling
- Button sizes
- Border radius (roundness)
- Shadows and depth
- Opacity/transparency

### Full Schema

See `user/custom-example.yaml` for complete documentation with all available properties.

## Design System

For consistent, professional skins, follow the design principles in:
`.interface-design/system.md`

Key principles:
- **Spacing scale**: Use 4/8/16/24/32 (not arbitrary values)
- **Color contrast**: Ensure text is readable
- **Token system**: Define values once, reuse everywhere

## Token System

Define values in `tokens` section, reference them anywhere:

```yaml
tokens:
  colors:
    accent: "#00BFFF"

video_player:
  styling:
    button_hover_color: "{tokens.colors.accent}"
    timeline_color: "{tokens.colors.accent}"
```

Benefits:
- Change one value, update everywhere
- Maintains consistency
- Easier to tweak themes

## Tips

1. **Start from existing skin**: Copy `modern-dark.yaml` as a base
2. **Use tokens liberally**: Define all colors/spacing in tokens section
3. **Test readability**: Ensure text has good contrast on backgrounds
4. **Iterate live**: Save file → switch skin → see changes instantly
5. **Share your skins**: Post awesome skins in TagGUI community!

## Troubleshooting

**Skin not showing up?**
- Ensure file is in `user/` or `defaults/` folder
- Check file extension is `.yaml` (not `.txt`)
- Validate YAML syntax (use online validator if needed)

**Skin looks broken?**
- Check for missing required fields (`name`, `version`)
- Verify token references use correct path (`{tokens.colors.primary}`)
- Look at console for error messages

**Want to reset?**
- Delete or rename custom skin file
- Switch back to a default skin (Modern Dark, Ocean, Volcanic)

## Advanced: Skin Engine

The skin system uses:
- **schema.py** - Defines what's customizable
- **skin_loader.py** - Loads and validates YAML files
- **skin_applier.py** - Applies skins to Qt widgets
- **skin_manager.py** - Orchestrates everything

You don't need to understand these to create skins, but if you want to add new skinnable properties, start with `schema.py`.

## Examples

### Minimal Skin
```yaml
name: "Simple Blue"
version: "1.0"

tokens:
  colors:
    primary: "#0080FF"

video_player:
  styling:
    timeline_color: "{tokens.colors.primary}"
```

### Full Custom Skin
See `user/custom-example.yaml` for comprehensive example with all options.

---

**Happy skinning!** 🎨

Share your creations with the TagGUI community!
