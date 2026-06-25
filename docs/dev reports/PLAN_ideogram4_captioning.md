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

## Next Phase: Editor

- Add an Ideogram caption dock showing the complete JSON caption.
- Synchronize background, high-level description, style, and element fields.
- Make the Ideogram overlay layer selectable and editable without reusing mask
  marking semantics.
- Save edits atomically to the detected caption or preferred sidecar path.
- Support creating a caption from existing TagGUI markings.
- Add import, copy, validation, compact/pretty view, and JSONL export actions.

## Generation Phase

- Add an Ideogram structured-output mode to local and remote auto-captioning.
- Disable flat tag insertion and caption text transformations in this mode.
- Optionally seed object elements from existing YOLO markings.
- Request descriptions for numbered locked regions while preserving coordinates.
- Parse and validate model output before replacing the saved caption.
- Add OCR/text-region support for exact visible text.
