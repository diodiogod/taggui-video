# Ideogram 4 Structured Caption Guide

[Back to Documentation Hub](HUB.md)

TagGUI can create, inspect, edit, search, and export Ideogram 4 structured JSON captions. These captions combine scene-level prose with typed object and text regions on a normalized bounding-box grid.

## Sidecar Format

The preferred sidecar name is:

```text
<media-name>.ideogram.json
```

TagGUI accepts a legacy sibling `.json` file only when its contents match the Ideogram caption structure. Normal `.txt` captions and TagGUI `.taggui.json` metadata remain separate.

The main fields are:

- `aspect_ratio`
- `high_level_description`
- optional `style_description`
- `compositional_deconstruction.background`
- `compositional_deconstruction.elements`

Each element is `obj` or `text`, has a description, and may contain a bounding box and color palette. Text elements also store the exact visible text. Bounding boxes use `[y1, x1, y2, x2]` coordinates on a `0-1000` grid.

## Creating a Caption

There are three main entry points.

### From Image Tags

When the current image has no Ideogram sidecar, hover the `Image Tags` title area and click `+ ID4`. This creates a structured caption with editable high-level description and background rows.

Once a sidecar exists, an `Ideogram` mode appears beside `Image Tags`. The existing `Add Tag` field then adds a new object region to the Ideogram caption instead of adding a normal text tag.

### From Existing Markings

Open `View -> Ideogram 4 Caption` and use the marking import action. TagGUI converts non-crop markings into object regions and avoids adding the same labeled coordinates twice. Overlapping but distinct regions are preserved.

If the Auto-Captioner starts an Ideogram caption without an existing sidecar, current markings are also used as locked seed regions.

### With the Auto-Captioner

Set `Output format` to `Ideogram 4 JSON`. TagGUI builds an image-specific prompt containing the aspect ratio and any existing Ideogram or marking regions. The generated result is validated and written to the preferred sidecar.

Local vision-language models and the `Remote` OpenAI-compatible backend can be used. WD Tagger is not compatible with Ideogram JSON output.

For remote generation, `Enforce JSON schema (remote)` optionally sends an OpenAI-compatible `response_format` schema. LM Studio supports this option. Leave it disabled for models or servers that reject structured output. Schema enforcement guarantees structure, not accurate descriptions or bounding boxes.

## Image Tags Integration

The `Ideogram` view in the Image Tags pane presents structured fields as visually distinct rows:

- high-level description
- background
- object elements
- text elements

Use the same interaction style as normal tags:

- double-click a row or press `F2` to edit it
- drag element rows to reorder them
- select a region row to select its viewer box
- press `Delete` to remove selected element rows
- right-click an element row to convert it between object and text
- use the normal `Add Tag` field to create object elements

Switching the description display to JSON shows the full structured caption rather than the compact rows.

## Main Viewer Editing

Ideogram regions are editable directly in the main viewer.

- Click and drag inside a region to move it.
- Drag any edge or corner to resize it.
- Smaller nested regions receive normal click priority.
- A selected larger region keeps resize priority on its own edges even when a smaller region overlaps it.
- Hold `Ctrl`, `Shift`, or `Cmd` while selecting to build a multi-selection.
- Resizing a multi-selection scales the selected regions together.
- Press `Delete` or `Backspace` to remove selected regions.
- Use `Ctrl+C` and `Ctrl+V` to copy and paste selected regions.
- Use `Ctrl+D` to duplicate selected regions while the viewer owns keyboard focus.
- Use `Ctrl+Z` or `Edit -> Undo` to undo region and marking edits recorded in history.
- Right-click a selected region to convert it between object and text.

By default, moving, resizing, or deleting an Ideogram region also updates a
uniquely matching TagGUI marking. Matching uses the region's pre-edit normalized
geometry and its label only to disambiguate exact duplicates; ordinary overlaps
are never treated as links. Disable this under `Settings -> Ideogram -> Region
Interaction` when the two region systems should remain independent.

The compact external label shows the element number and `OBJ` or `TEXT`. The text inside the region shows the description without repeating the type.

## Color Palettes

TagGUI samples dominant colors from each region. The primary color is saved in the JSON; additional sampled candidates are shown as choices in the editor and viewer.

- Click a displayed palette candidate to make it primary.
- Use `Pick` in the Ideogram caption panel to sample a pixel from the image.
- Use the automatic palette action to discard a manual override and resume automatic sampling.
- Moving or resizing an automatically colored region recalculates its sampled colors after a short debounce.
- Palette strips hide when a region is too small on screen and reappear after zooming in.

If color picking was started for a region that is completely outside the viewport, clicking inside another visible region retargets the picked color to the smallest region under the pointer. A partially visible original region remains the target.

## Dedicated Ideogram Panel

Open `View -> Ideogram 4 Caption` for full structured editing. The panel supports:

- paste or import complete JSON
- format, validate, and save JSON
- edit high-level, background, style, element, text, bounding-box, and palette fields
- add, duplicate, delete, and reorder elements
- import TagGUI markings
- export valid folder sidecars to a JSONL manifest

The JSONL export stores each structured caption as a JSON string in its `caption` field.

## Overlay Settings

Open `Settings -> Ideogram` to adjust the viewer presentation live:

- external label font size and weight
- label outline, padding, colors, and background opacity
- region line width and contrast halo
- in-box description size, color, text opacity, and background opacity

These settings affect display only. They do not alter caption content.

## Filtering and Database Indexing

Plain searches and `caption:` searches include searchable Ideogram text. Dedicated filters are also available:

```text
ideogram:"bridge tower"
ideogram_color:"#34D6C7"
```

Ideogram caption text and palette terms are indexed in the folder database for paginated filtering. The sidecar remains the source of truth, and the index is reconciled from sidecars during folder scanning and refresh.

## Notes

- Automatic captions require human review for training-quality descriptions.
- Structured output constrains JSON syntax and shape but cannot guarantee semantic correctness.
- Existing locked boxes keep their coordinates when the captioner enriches their descriptions.
- Copying or importing JSON replaces the structured caption only after validation succeeds.

## Continue Reading

- [Captioning Guide](CAPTIONING_GUIDE.md)
- [Markings Guide](MARKINGS_GUIDE.md)
- [Filtering Guide](FILTERING_GUIDE.md)
