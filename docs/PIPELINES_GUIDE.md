# Pipelines Guide

[Back to Documentation Hub](HUB.md)

Pipelines combine TagGUI automation tools into named, reusable ordered workflows. They are typed operations, not recorded mouse or keyboard macros, so a pipeline continues to work when docks are hidden or rearranged.

Open `View -> Pipelines` to create and run workflows.

## Visual Editor

Each operation appears as a card on the execution spine. The numbered glowing nodes show the exact run order.

- Drag the `::::` handle to reorder a card.
- Scroll over the step list for controlled pixel-by-pixel navigation.
- Hold `Ctrl` and scroll anywhere over a step to resize all cards between
  compact and expanded densities. The chosen density is remembered.
- Hold `Ctrl` and scroll over the surrounding pipeline controls to resize the
  hero, profile, Add Step, scope, status, and run UI independently of cards.
- The dock can be compressed to a minimal footprint. At extreme sizes,
  lower-priority controls may clip instead of forcing neighboring docks larger.
- Use `Edit` to expand model and generation settings.
- Clear a card's checkbox to keep it in the profile without running it.
- Use `+ Add step` to append another operation.
- Edit the pipeline name directly in the pipeline selector.
- Use `Copy` to duplicate the current pipeline.
- Use the `...` menu to import or export a pipeline JSON file.

Profiles are saved automatically in the user's TagGUI configuration directory.

## Step Types

### Auto Marking

Runs one YOLO auto-marking model across the selected scope.

Configure:

- model path, relative to the configured auto-marking models directory or absolute
- output marking type: hint, exclude, or include
- optional comma-separated model class names and output-label overrides
- confidence, IoU, and maximum detections

If no class names are supplied, every class exposed by that model is used. Exact matching results already present on an image are skipped; distinct overlapping regions remain valid.

Use `source_class{output label}` to rename generated markings without changing the detector class used for inference. For example, `eye{person eye}, hand, tool{held tool}` detects the model classes `eye`, `hand`, and `tool`, then saves the first and third labels as `person eye` and `held tool`. Plain entries such as `hand` keep the model's original label. Class matching is case-insensitive.

Double-click the `Classes / labels` field label to populate the field with every
default class from the selected YOLO model. Existing filters or custom mappings
require confirmation before they are replaced.

Add several Auto Marking cards to detect faces, hands, tools, or other model-specific regions in sequence. Pipeline execution is stage-major, so each model handles the full scope before the next model loads.

Click `+ Add step` to append a stage, or drag it into the card list. A cyan
insertion line shows the destination; releasing opens the step-type menu and
inserts the selected stage at that position.

#### Linked Auto-Marking Steps

Drag the chain icon from one Auto-Marking card onto an adjacent Auto-Marking
card to merge their same-label, same-marking-type detections before they are
written. The live cyan connector and target highlight show whether the drop is
valid. Linked cards retain a cyan connector and a `LINKED` summary badge.

- Link the model classes to a shared output label, such as `hand`, using the
  existing `source_class{output label}` syntax.
- Plain class names inherit persistent custom labels from the Auto Markings
  panel for the same model. Explicit `{output label}` mappings take priority,
  and classes without either customization keep the model's default label.
- Double-click `Classes / labels` to import all model classes and snapshot any
  saved custom labels as explicit `source{output label}` mappings.
- Configure `Linked overlap` on either card; the threshold is shared by every
  card in that linked group.
- Overlapping detections meeting the threshold become one union bounding box
  with the highest confidence from the group.
- Non-overlapping detections remain separate, so two independently located
  hands still produce two markings.
- Linked detections are buffered until the final linked model completes and
  create one undo action for the whole group.

Linked cards must remain adjacent because following steps may consume their
results. Reordering or deleting cards automatically removes links that no
longer form a valid adjacent group. Click a linked chain icon to unlink that
card; click an unlinked chain to display the drag instruction.

### Build Ideogram Regions

Converts current non-crop TagGUI markings into Ideogram object elements. Existing structured captions are preserved, exact duplicate regions are skipped, and new sidecars use the image aspect ratio.

### Auto Caption

Runs the existing Auto-Captioner service after earlier pipeline steps have prepared the image metadata.

Configure:

- local model, downloaded model ID, or `Remote`
- `Ideogram 4 JSON` or `Plain caption` output
- optional remote JSON-schema enforcement

Settings not shown on the card, such as the endpoint, API key, prompt, generation parameters, and video sampling, come from the current Auto-Captioner configuration.

### Synchronize Search Indexes

Refreshes searchable database state for tags, markings, ratings, reactions,
review state, and Ideogram captions. It does not rewrite `.txt`, `.taggui.json`,
or Ideogram caption sidecars.

Normal pipeline operations save their own output immediately, so this optional
maintenance step is not included in new default pipelines. Add it when database
search data needs explicit reconciliation, such as after index maintenance.

## Scopes

- `Current image`: run only on the image shown by the active browser.
- `Selected images`: run on the active browser's current selection.
- `Filtered images`: run on images exposed by the active browser's filter.
- `All images`: run on the active browser's complete source model.

Browser 1 and Browser 2 keep independent source models, undo history, sidecars,
and search indexes. Pipeline results are applied to whichever browser is active
when the run starts.

## Running

Click `Run pipeline`. The active card and flow node highlight while the status panel reports per-stage progress. Open `Log` for operation messages. The run button becomes `Cancel pipeline` while work is active.

Long model stages run asynchronously. Synchronous conversion and save stages remain cancellable between images.

## Example

An Ideogram dataset pipeline can use:

1. Auto Marking with a face detector.
2. Auto Marking with a hand detector.
3. Auto Marking with a tool detector.
4. Build Ideogram Regions.
5. Auto Caption using `Ideogram 4 JSON`.

This produces a structured caption scaffold from all detector regions before the vision-language model expands their descriptions.

## Current Boundaries

- Pipeline profiles are global to the current user rather than embedded in a dataset.
- Auto-caption cards reuse detailed settings from the Auto-Captioner panel.
- Auto-marking reruns exact-deduplicate generated regions but do not yet track per-run provenance.
- Pause/resume checkpoints and retry-failed controls are planned after the initial runner foundation.

## Continue Reading

- [Markings Guide](MARKINGS_GUIDE.md)
- [Captioning Guide](CAPTIONING_GUIDE.md)
- [Ideogram 4 Structured Caption Guide](IDEOGRAM4_GUIDE.md)
