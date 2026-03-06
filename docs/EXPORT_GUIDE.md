# Export Guide

TagGUI Video 1M includes a non-destructive export workflow for preparing images and masks for training or dataset cleanup.

This export path is separate from `Apply crop to file`, which modifies the source file directly.

## What Export Does

The export dialog lets you:

- choose which images to export
- resize or bucket-fit exported images
- apply crop/include/exclude markings
- generate captions and sidecar text files
- preserve directory structure or flatten output
- export masks as separate files when needed

Open it from:

- `File -> Export...`

## Image Selection

The export dialog supports different image-selection scopes:

- all images
- filtered images
- selected images

This makes export useful for both:

- whole-dataset export
- smaller targeted batches after filtering or selection

## Crop and Marking Interaction

Export uses the marking system directly.

- `Crop` defines the main export boundary
- `Include` keeps only marked regions when include markings exist
- `Exclude` removes marked regions from the exported result
- `Hint` is annotation only and does not change export pixels

Important behavior:

- if no include markings exist, the full cropped area stays included
- if include and exclude overlap, exclude takes precedence
- when export settings require bucket fitting, TagGUI may crop further than the visible crop box

This is why the crop guide can show extra trimmed areas during crop editing.

## Resolution and Bucket Fitting

The export dialog includes several settings that work together:

- `Resolution (px)`
- `Bucket resolution size (px)`
- `Latent size (px)`
- `Allow upscaling`
- `Bucket fitting strategy`
- `Preferred sizes`

### Resolution

`Resolution` is the target export scale.

Common values already hinted in the UI include:

- `0` to disable rescaling
- `512` for SD1.5-style workflows
- `1024` for SDXL, SD3, and Flux-style workflows

### Bucket Resolution Size

`Bucket resolution size` forces export sizes to stay divisible by a configured step size.

This should match the expectations of the training workflow you are preparing for.

### Bucket Fitting Strategy

The export dialog supports:

- `crop`
- `scale`
- `crop and scale`

In practice:

- `crop` keeps geometry cleaner but may trim more
- `scale` avoids extra crop but can distort aspect ratio more
- `crop and scale` balances both

### Preferred Sizes

`Preferred sizes` lets you bias export toward specific size pairs or aspect ratios.

This is useful when you already know your preferred bucket set.

## Masking Strategy

Masking controls how exclude/include markings affect the exported result.

Available strategies include:

- ignore masks
- replace masked content
- remove masked content when the output format supports alpha
- create mask files

The exact available labels come from the export dialog, but the practical choices are:

- keep everything
- bake masking into the output image
- export masks separately

## Masked Content

When masking is baked into the exported image, TagGUI can replace masked areas with different kinds of content.

The dialog supports options such as:

- blur
- blur + noise
- grey
- grey + noise
- black
- white

This is useful when you want masked areas to stay visually neutral instead of transparent.

## Latent Alignment and Alpha Quantization

The export dialog includes:

- `Latent size (px)`
- `Quantize alpha channel`

These settings matter when include and exclude masks are part of the export.

Practical effect:

- exclude regions may expand slightly
- include regions may shrink slightly
- the mask aligns better to the training/export grid

This is especially relevant for latent-space training workflows.

## Output Format and Color

Export supports multiple image formats, depending on what Pillow can save in the current environment.

The dialog also lets you choose:

- output format
- quality
- output color space

Important behavior:

- JPEG does not support alpha
- some masking strategies are limited by output format
- color-space conversion can be applied during export

## Caption Export

Export can also write matching `.txt` caption files into the export folder.

TagGUI already saves your working tags and text beside the source files during normal use.

The export workflow uses that saved tagging data to create a new exported dataset:

- exported image in the export folder
- exported `.txt` file beside that exported image

The exported `.txt` file is generated from the saved tags according to the export settings, instead of being copied blindly as-is.

The dialog includes settings for:

- caption algorithm
- filtering out `#` tags
- handling `#newline`

This is useful when you want the exported image and exported text to stay aligned as a clean output dataset.

## Output Directory Behavior

You can configure:

- export directory
- whether to keep input directory structure

If the destination is not empty, the export flow can:

- export only missing images
- refresh captions
- rename outputs to avoid collisions

This makes repeated export passes safer when you are iterating on captions or masks.

## Exported Mask Files

When mask-file export is enabled:

- images are exported into an image output path
- masks are exported into a parallel mask output path

This is useful when your downstream workflow expects image and mask pairs as separate files.

## Destructive Crop vs Export

Do not confuse these two workflows:

- `File -> Export...` is non-destructive and writes new files
- `Apply crop to file` modifies the original file in place

`Apply crop to file` does create a backup, but it still changes the working file directly.

For normal dataset preparation, export is the safer default.

## Related Docs

- [Markings Guide](MARKINGS_GUIDE.md)
- [Filtering Guide](FILTERING_GUIDE.md)
- [Captioning Guide](CAPTIONING_GUIDE.md)
- [Installation](INSTALLATION.md)
