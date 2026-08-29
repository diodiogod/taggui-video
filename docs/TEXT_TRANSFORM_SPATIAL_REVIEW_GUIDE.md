# Text Transform and Spatial Caption Review Guide

[Back to Documentation Hub](HUB.md)

TagGUI includes two related tools for manually reviewing and correcting caption
wording:

- **Text Transform** performs configurable text replacement or atomic two-way
  swaps.
- **Spatial Caption Review** highlights potentially ambiguous left/right and
  positioning language, then offers explicit manual corrections.

Neither feature automatically decides that a captioning model is wrong.
Highlighting is a review prompt only; captions change only after a user applies
a correction.

## Why Spatial Review Exists

Vision-language captioners can confuse several different uses of left and
right:

- the subject's anatomical left or right
- the viewer's left or right
- the left or right side of the image or video frame

For example, `his right hand` and `the hand on the right side of the frame` do
not necessarily describe the same hand. TagGUI therefore avoids automatic
conversion. It makes the expression easy to notice and lets the user compare
the caption with the visible media before choosing a correction.

## Opening Text Transform

Open the compact Text Transform window in any of these ways:

- click the `⇄` button in the Image Tags title bar
- choose `Edit -> Text Transform...`
- press `Ctrl` + `Shift` + `T`
- right-click a normal caption row or descriptive caption text and choose
  `Send to Text Transform...`

Text Transform is an independent tool window, not a dock. It cannot attach to
the existing TagGUI panels. It remembers its position, last operation, scope,
matching options, and saved presets.

Press `Esc` to hide it without losing the current configuration.

## Replace and Swap Modes

Text Transform has two main modes:

- **Replace (`A -> B`)** changes occurrences of A into B.
- **Swap (`A <-> B`)** exchanges A and B in one atomic operation.

Atomic swapping is important. A left/right swap does not first replace every
`left` with `right` and then accidentally replace those new values again.

Built-in presets include:

- Left / Right
- His / Her
- Man / Woman
- Foreground / Background
- Day / Night

Use the `...` preset menu to save the current values as a named preset or
delete a custom preset. Built-in presets remain available.

## Transform Scopes

The scope selector supports:

- `Selected text`: only the current selection in descriptive mode
- `Selected caption rows`: selected rows in the normal Image Tags view
- `Current media caption`: the complete caption for the current image or video
- `Selected media`: captions belonging to selected media
- `Filtered media`: captions in the current filtered result
- `All media`: every caption in the open folder

Batch scopes show the affected caption and replacement counts before applying
changes and require confirmation.

For paginated folders, `All media` is supported through the folder index and
caption sidecars. Selected and filtered batch scopes are unavailable in
paginated mode; use a current-caption scope or `All media` instead.

## Matching Options

Expand `Options` in the Text Transform window to configure:

- `Whole words`: prevents a value such as `cat` from changing the `cat` inside
  `catfish`
- `Preserve capitalization`: carries common uppercase, lowercase, and
  initial-capital patterns into the replacement
- `Match case`: requires the source text to use the entered capitalization
- `Regex`: interprets A as a regular expression

Regex replace mode supports normal replacement back-references. Swap mode
treats A and B as the two expressions that identify each side of the swap.

Use `Preview` to count matches without modifying captions. `Apply Last Text
Transform` in the editor context menu or `Ctrl` + `Alt` + `T` repeats the
configured operation and scope.

## Spatial Highlighting

Potentially ambiguous spatial phrases are highlighted in amber:

- normal Image Tags rows use amber text and display a small `↔` gesture handle
- descriptive mode highlights the detected phrase directly

Examples include:

- `his left hand`
- `her right shoulder`
- `their left leg`
- `a person on the right`
- `on the left side of the frame`

The detector uses a controlled expression vocabulary rather than asking a
caption model to reinterpret the media. Supported body parts include hands,
arms, legs, feet, eyes, ears, cheeks, eyebrows, temples, shoulders, elbows,
wrists, fingers, hips, knees, calves, thighs, ankles, buttocks, and body sides.

Correcting one phrase in descriptive mode marks only that phrase as checked.
Other directional phrases in the same caption remain highlighted until they
are independently reviewed. A correction applied to a selected tag row can
affect every matching expression in that row. Review state is stored in TagGUI
metadata and does not add markers to the exported `.txt` caption.

## Right-Click Spatial Corrections

Right-click a highlighted caption row or phrase and open `Spatial Correction`.
Depending on the detected expression, the menu can offer:

- `Set Body Direction to Left`
- `Set Body Direction to Right`
- `Convert to Frame Left` or `Convert to Frame Right`
- `Convert to Image Left` or `Convert to Image Right` when Image wording is
  selected in Settings
- `Set Position to Background`
- `Set Position to Foreground`
- `Mark Direction as Checked / Ignore Highlight`
- `Restore Direction Highlight`

Unavailable transformations are disabled for the selected expression.

Examples:

```text
his left hand -> his right hand
his left hand -> his hand on the right side of the frame
his left hand -> his left hand in the background
a woman on the left -> a woman on the right side of the frame
```

`Mark Direction as Checked / Ignore Highlight` suppresses every spatial
highlight in the selected row without editing its caption. Normal corrections
track reviewed phrases individually.

## Left-Drag Correction Disk

Spatial corrections can also be applied with one left-button gesture.

In normal tag mode, begin the drag on the small amber `↔` handle. In
descriptive mode, begin on the highlighted phrase itself. A normal click does
not change the caption; the disk activates only after the pointer crosses the
drag threshold.

For anatomical body expressions:

- short drag left: set the body direction to left
- short drag right: set the body direction to right
- long drag left: convert to the left side of the selected frame/image
  reference
- long drag right: convert to the right side of the selected frame/image
  reference

Depth gestures are also available:

- drag up: place the expression in the background
- drag down: place the expression in the foreground
- drag diagonally: combine background/foreground with the chosen frame/image
  side

The disk shows the proposed caption text before release. Return to its center
to cancel. Moving farther beyond an outer target keeps that target selected, so
a fast or forceful flick remains valid rather than being rejected for
overshooting.

## Spatial Review Settings

Open `Settings -> Spatial Review` to configure the feature globally.

### Highlight spatial expressions

Enables or disables left/right and spatial review highlighting. It does not
edit existing captions.

### Enable left-drag correction disk

Enables the gesture interaction and tag-row handles. Right-click corrections
and Text Transform remain available when gestures are disabled.

### Highlight foreground/background expressions

Controls only whether standalone foreground/background wording is highlighted
for review. It defaults to off because depth wording is generally less
ambiguous than anatomical versus viewer-relative left/right.

This setting does **not** remove foreground/background corrections from the
disk. For example, `his right arm` can still be dragged downward to produce
`his right arm in the foreground`.

### Position reference wording

Choose the noun used for viewer-relative output:

- `Frame`: `on the right side of the frame`
- `Image`: `on the right side of the image`

Frame wording works for both still images and video frames. Image wording is
available for datasets that prefer conventional still-image caption language.

## Manual-Review Boundary

Spatial Caption Review follows these rules:

- detection and highlighting may happen automatically
- interpretation and correction are always manual
- no captioning model is called to verify direction
- no detected expression is silently rewritten
- foreground/background is added only after an explicit user action

A future model-assisted verifier could ask a focused spatial question and
present its answer as a suggestion, but that is not part of the current
workflow.

## Undo and Safety

- Text changes made through the editor use the normal caption synchronization
  and sidecar paths.
- Batch Text Transform operations create an undo checkpoint and show a preview
  count before confirmation.
- Spatial checked/ignored state is TagGUI metadata; it does not contaminate
  caption text.
- Use a small selection or current-caption scope when first testing a custom
  regex or preset.

## Related Guides

- [Captioning Guide](CAPTIONING_GUIDE.md)
- [Shortcuts](SHORTCUTS.md)
- [Filtering Guide](FILTERING_GUIDE.md)
- [Ideogram 4 Structured Caption Guide](IDEOGRAM4_GUIDE.md)
