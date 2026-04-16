# Masonry Review Wall Guide

[Back to Documentation Hub](HUB.md)

This guide covers the selection masonry wall and the review badge workflow.

It is designed for fast comparison of multiple images or videos in separate floating windows, especially when you want to sort many similar generations and mark picks, rejects, questions, or custom badge meanings.

## What It Is

- The masonry review wall opens the current selection as a wall of floating viewers.
- It keeps the top aligned and packs the windows in a masonry-style arrangement across the current screen.
- Mixed images and videos are supported.
- If the wall contains multiple videos, video sync and playback start automatically.
- The wall works together with the review badge system, so you can mark files while comparing them.

<p align="center">
  <img src="../images/masonry-review-wall.jpg" alt="Masonry review wall with review badges" width="86%">
</p>

## Open The Masonry Wall

- Select two or more items in the image list.
- Right-click and choose `Open ... in Masonry Wall`.
- Or press `Ctrl` + `Shift` + `Enter`.
- Or drag a multi-selection from the image list and release it to open the wall directly.

Single-item spawn is still available. The masonry wall is for multi-item review.

## Why Use It

- Compare many similar generations at once.
- Review short video variants side by side.
- Keep the main window available while using floating viewers for decisions.
- Mark picks and rejects without leaving the comparison workflow.

## Review Badges

Review badges are item-level marks stored separately from normal tags.

They are meant for review workflow state, not caption content. A badge can mean whatever you want it to mean in your workflow.

Current default badge set:

- `1 2 3 4 5`
- `*`
- `!`
- `?`
- `X`

All symbolic badges are stackable. Numeric badges act like a single rank slot.

## Add Badges In The Wall

- Hover a masonry wall viewer to reveal the 3x3 badge slots.
- Click a slot to add or remove that badge from that file.
- After hover leaves, active badges stay visible on that viewer.
- Hover a badge slot to see the generic tooltip.

This makes the wall usable as a direct review surface instead of only a comparison layout.

## Review Toolbar

The detachable `Review toolbar` gives you the same badge actions outside the wall overlay.

- Click badge buttons to add or remove review marks.
- Use `Clear -> Clear Selected` to clear badges from the current review target.
- Use `Clear -> Clear Current Folder` to clear all review badges in the loaded folder.

`Clear Current Folder` shows a confirmation dialog before it runs.

## Badge Settings

`Settings -> Badges` lets you customize the current badge system without changing the number of slots.

You can change:

- badge symbol/label
- optional hover title
- badge color
- shortcut mapping
- text color
- font size
- corner roundness

These settings apply live across:

- the review toolbar
- the masonry wall overlay
- image-list badges

## Keyboard Shortcuts

Default review shortcuts:

- `1` to `5` for numeric rank badges
- `8` or `Shift` + `8` for `*`
- `?` for question
- `X` for reject
- apostrophe/quote key for warning

The exact mappings may differ if you customized them in `Settings -> Badges`.

## Image List Behavior

- Review badges also appear on thumbnails in the image list.
- They persist across reloads because they are saved in the folder DB and JSON sidecars.
- Filtering can use review predicates such as `review:true`, `review:reject`, `review:idea`, and `review_rank:>=2`.

## Related Docs

- [Floating Viewers User Guide](FLOATING_VIEWERS_USER_GUIDE.md)
- [Compare Guide](COMPARE_GUIDE.md)
- [Filtering Guide](FILTERING_GUIDE.md)
- [Shortcuts](SHORTCUTS.md)
