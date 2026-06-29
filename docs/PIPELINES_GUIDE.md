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

Add several Auto Marking cards to detect faces, hands, tools, or other model-specific regions in sequence. Pipeline execution is stage-major, so each model handles the full scope before the next model loads.

### Build Ideogram Regions

Converts current non-crop TagGUI markings into Ideogram object elements. Existing structured captions are preserved, exact duplicate regions are skipped, and new sidecars use the image aspect ratio.

### Auto Caption

Runs the existing Auto-Captioner service after earlier pipeline steps have prepared the image metadata.

Configure:

- local model, downloaded model ID, or `Remote`
- `Ideogram 4 JSON` or `Plain caption` output
- optional remote JSON-schema enforcement

Settings not shown on the card, such as the endpoint, API key, prompt, generation parameters, and video sampling, come from the current Auto-Captioner configuration.

### Save Metadata

Flushes normal captions, TagGUI marking metadata, Ideogram sidecars, and searchable Ideogram indexes.

## Scopes

- `Current image`: run only on the image shown in Browser 1.
- `Selected images`: run on the current Browser 1 selection.
- `Filtered images`: run on images currently exposed by the active Browser 1 filter.
- `All images`: run on the complete Browser 1 source model.

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
6. Save Metadata.

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
