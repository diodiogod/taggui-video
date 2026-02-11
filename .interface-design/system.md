# TagGUI Design System

## Direction
**Speed with Style** — Modern, sleek dataset visualizer that's fast and beautiful

## Principles
1. **Performance as aesthetics** — Speed creates delight, lag destroys experience
2. **Visual hierarchy through polish** — Clean lines, smooth surfaces, purposeful contrast
3. **Masonry as signature** — Stylish grid layouts define the experience
4. **Modern minimalism** — Sleek, contemporary, refined without ornamentation

---

## Foundation

### Spacing Scale
```
xs:  4px  — Tight clustering (icon padding, inline gaps)
sm:  8px  — Related elements (button groups, inline controls)
md: 16px  — Section separation (control groups, rows)
lg: 24px  — Major sections (panels, dialogs)
xl: 32px  — Page-level spacing
```

**Rule**: Never use arbitrary values (7px, 13px). Always use scale.

### Typography
```
Base:       12px (body text, labels)
Emphasis:   14px (section headers)
Display:    16px (page titles)
Small:      10px (metadata, timestamps)
```

**Weights**: Regular (400), Bold (700)

### Color Tokens

#### Neutrals (Modern Dark)
```
background-primary:   #0D0D0D  — Main canvas (deep black for OLED-like depth)
background-secondary: #1A1A1A  — Elevated surfaces (panels, dialogs)
background-tertiary:  #242424  — Nested surfaces (control bars)
border:               #333333  — Subtle dividers (higher contrast)
border-accent:        #404040  — Emphasized dividers
text-primary:         #FFFFFF  — High emphasis text (pure white)
text-secondary:       #B0B0B0  — Medium emphasis (labels)
text-tertiary:        #707070  — Low emphasis (disabled)
```

#### Functional
```
primary:        #2196F3  — Actions, focus states
primary-hover:  #1976D2  — Interactive hover
accent:         #00B4D8  — Highlights, selections
success:        #4CAF50  — Confirmations, success states
warning:        #FFA726  — Cautions, warnings
error:          #F44336  — Errors, destructive actions
```

### Depth (Shadows & Elevation)

```
level-0: none               — Flat surfaces
level-1: 0 2px 4px rgba(0,0,0,0.2)   — Buttons, cards
level-2: 0 4px 8px rgba(0,0,0,0.3)   — Overlays, tooltips
level-3: 0 8px 16px rgba(0,0,0,0.4)  — Modals, popups
```

### Surface Treatment

```
corner-radius:
  tight:    4px   — Subtle rounding (inputs, small buttons)
  normal:   6px   — Standard (buttons, panels)
  relaxed:  12px  — Prominent elements (cards, dialogs)

borders:
  hairline: 1px solid {border}
  emphasis: 2px solid {primary}
  glow:     0 0 8px {primary}40 (40% opacity glow for focused states)

glass-morphism:
  background: {background-tertiary} @ 0.85 opacity
  backdrop-blur: 8px (simulated via layering)
  border: 1px solid {border-accent}
```

### Opacity

```
overlay:      0.85  — Background overlays
control-bar:  0.95  — Semi-transparent controls
disabled:     0.50  — Disabled states
hover:        0.08  — Hover tints (layer over base color)
```

---

## Component Patterns

### Buttons
```
Height:     32px (compact), 40px (comfortable)
Padding:    8px horizontal (tight), 16px (normal)
Border:     1px solid {border} (default), 2px solid {primary} (focused)
Radius:     4px
Text:       12px, bold
States:
  default:  bg={background-tertiary}
  hover:    bg={background-tertiary} + 8% overlay
  active:   bg={primary}
  disabled: opacity=0.5
```

### Sliders
```
Track height:    8px
Handle size:     16px (width) × 20px (height)
Handle radius:   8px (circular ends)
Track radius:    4px
Colors:
  track-bg:      {background-secondary}
  track-fill:    {primary}
  handle:        #FFFFFF
  handle-border: #333333 (2px)
```

### Control Bars
```
Height:      60px (video controls)
Background:  {background-tertiary} @ 0.95 opacity
Padding:     8px vertical, 16px horizontal
Shadow:      level-2
```

### Spacing Between Elements
```
Button groups:      8px (sm)
Control sections:  16px (md) — Use addSpacing(16)
Major sections:    24px (lg)
```

---

## Video Player Specific

### Loop Markers
```
Shape:         Triangle (18px base × 14px height)
Colors:
  start:       #FF0080 (pink/magenta) + white outline (2px)
  end:         #FF8C00 (orange) + white outline (2px)
Position:      Above slider groove (-2px from top)
```

### Speed Slider Gradients
**Theme structure**: 3-color gradient (start, mid, end)
- Default: Volcanic (#2D5A2D → #6B8E23 → #32CD32)
- See video_controls.py:454-481 for full theme list

### Timeline
```
Height:         8px
Position:       Above control bar (integrated)
Progress color: {primary}
Background:     {background-secondary}
```

---

## Rules for Skins

When creating new skins (themes):

1. **Maintain spacing scale** — Always use 4/8/16/24/32, never arbitrary
2. **Preserve contrast ratios** — Ensure text remains readable (4.5:1 minimum)
3. **Respect functional color roles** — Error must look like error, success like success
4. **Keep depth hierarchy** — Overlays must elevate, not flatten
5. **Test all states** — Default, hover, active, disabled, focused

User-created skins SHOULD follow these principles for consistency, but MAY deviate for creative expression (within usability bounds).

---

## Implementation Notes

- This system guides default skin creation (`default.yaml`, `dark.yaml`)
- Skin engine validates against schema but allows override
- Token references use `{tokens.colors.primary}` syntax in YAML
- All measurements in pixels unless specified
