# Ideogram 4 Structured Captioning

## Implemented Foundation

- Detect `media.ideogram.json` automatically.
- Accept `media.json` only when it matches the Ideogram caption schema.
- Parse and validate object/text elements, palettes, styles, and normalized
  `[y1, x1, y2, x2]` bounding boxes.
- Serialize canonical compact JSON and save to `media.ideogram.json`.
- Draw read-only numbered overlays in the main viewer.
- Show an error badge without modifying invalid JSON.
- Provide a persistent `I4` toolbar visibility toggle.
- Add an Ideogram caption dock showing the complete JSON caption.
- Save valid edits atomically to the detected caption or preferred sidecar path.
- Preserve temporarily invalid edits as per-image in-memory drafts.
- Support creating a caption from existing TagGUI markings.
- Add reload, copy, validation, and readable formatting actions.

## Next Phase: Visual Editor

- Synchronize background, high-level description, style, and element fields.
- Make the Ideogram overlay layer selectable and editable without reusing mask
  marking semantics.
- Add element reordering, object/text conversion, and palette editing.
- Add explicit import and compact/pretty output controls.
- Add dataset-level JSONL export.

## Generation Phase

- Add an Ideogram structured-output mode to local and remote auto-captioning.
- Disable flat tag insertion and caption text transformations in this mode.
- Optionally seed object elements from existing YOLO markings.
- Request descriptions for numbered locked regions while preserving coordinates.
- Parse and validate model output before replacing the saved caption.
- Add OCR/text-region support for exact visible text.
