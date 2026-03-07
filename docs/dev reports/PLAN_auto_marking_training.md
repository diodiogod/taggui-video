# Auto-Marking Training Plan

Small future plan for bringing YOLO training closer to TagGUI without turning
the app into a full ML platform.

## Goal

Let users turn manual TagGUI markings into a trainable YOLO dataset, fine-tune
or train a model, and load the resulting `.pt` back into Auto-Markings.

## Minimal Plan

1. Export current markings to YOLO dataset format
- export images plus label files
- map TagGUI marking labels to YOLO classes
- generate a simple train/val split

2. Add a lightweight training launcher
- choose base model
- choose dataset export folder
- set basic options like epochs, image size, batch, and device
- stream training logs into a dock/panel

3. Round-trip the trained model back into Auto-Markings
- save trained weights into the marking models folder
- make the new `.pt` selectable immediately in Auto-Markings

## Non-Goals For First Version

- full experiment tracking
- dataset versioning
- advanced augmentation UI
- hyperparameter search
- cloud training integration

## Notes

- The hard part is dataset quality, not the YOLO training command itself.
- This feature makes the most sense as an annotation/export + training launcher
  workflow, not as a full labeling platform replacement.
- OCR may still be a better fit than YOLO for highly variable watermark text.
