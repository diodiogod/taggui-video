# Troubleshooting

Use this page only for real, current issues that are already known to happen in TagGUI Video 1M.

## Folder Cache or Database Feels Wrong

If thumbnails, dimensions, or folder metadata look stale or inconsistent:

- open `Settings`
- use `Clear Current Directory Cache`
- reload the folder and let TagGUI rebuild its cache

This clears the current folder's:

- image index database bundle
- thumbnail cache entries for that folder

Use this when:

- a folder changed outside TagGUI
- thumbnails look wrong
- metadata feels stale
- masonry layout looks inconsistent after folder changes

## Selected Thumbnail Looks Wrong or Has the Wrong Dimensions

> [!NOTE]
> TagGUI has a developer-oriented repair shortcut for thumbnail or dimension mismatches.

- Select the broken item
- press `Ctrl` + `Shift` + `D`

This repair action can:

- clear stale in-memory thumbnail data
- delete the corresponding disk thumbnail cache entry
- re-read dimensions from disk
- update the DB entry
- force a masonry refresh

This is not meant as a normal everyday action, but it is useful when one or a few items are clearly wrong.

## Floating Viewers Are Getting in the Way

If you have many spawned viewers open and they are blocking the main app:

- press `H` to hold existing spawned viewers
- or middle-click in the main window or image list area
- or use `Close all spawned viewers`

Hold mode keeps the viewers visible but turns them into dimmed, click-through overlays so you can keep working.

## Video Playback Looks Wrong

> [!NOTE]
> Backend behavior can differ. The project currently prefers the MPV path for playback.

If video behavior feels off:

- confirm whether the issue is playback smoothness, frame accuracy, or seeking behavior
- remember that not all backend paths behave the same way
- if the issue persists, it should likely be documented later in a dedicated backend guide

## Large Folder Takes Time on First Open

The first open of a large folder can take longer because TagGUI may need to:

- scan the folder
- build or refresh the per-folder database
- generate or validate thumbnails

Later opens should usually be faster unless cache or database data was cleared.

## Skin Designer Bug or Broken Skin Behavior

The skin system works, but the skin designer is still an experimental part of the project.

If something in skin editing or skin application looks wrong:

- verify the issue with a built-in skin first
- if it is reproducible, open a GitHub issue
