# Quick Sort Guide

[Back to Documentation Hub](HUB.md)

Quick Sort is a focused, keyboard-driven workflow for rapidly organizing images and videos into folders. It snapshots the chosen browser scope when the session starts, shows one item at a time, and advances after each completed decision.

## Start Immediately

1. Load a folder in Browser 1 or Browser 2.
2. Open `Quick Sort` from the menu, or press `Ctrl + Shift + Q` when the saved setup is ready.
3. Press any letter `A-Z` or number `0-9`.

No destination setup is required. By default, pressing `R` routes the current file into folder `R`, pressing `1` routes it into folder `1`, and so on. Destination folders are created below the active folder unless a different parent is selected.

## Named Destination Overrides

Use `Add named override` only when a key should be more descriptive or use another relative folder. Each compact row contains:

- **Key:** the keyboard key used during sorting.
- **Name:** the label shown as visual feedback.
- **Folder:** the relative destination, including optional nested paths.
- **Color:** the small feedback accent.

For example, an override can map `R` to the visible name `Right Arm` and folder `Body/Right Arm`. That override replaces the automatic `R` folder while the remaining standard keys continue to work normally. Disable `Automatically map A-Z and 0-9` when a profile should accept only explicitly configured destinations.

## Images Included in a Session

The compact `Sort` control describes the queue source; it does not add another folder watcher.

- **Current folder:** media from the active browser folder, optionally including subfolders.
- **Selected media:** only the current browser selection.
- **Filtered results:** the current filtered result set.
- **All loaded media:** everything in the active browser scope.

The queue is immutable. Destination folders created during sorting are not scanned back into the same session.

## Resuming and Skipped Images

Quick Sort remembers sorted and skipped decisions immediately for each profile, source folder, and scope. Exiting or restarting TagGUI does not send those files through the normal sequence again. The next run resumes at the first unreviewed item; skipped files remain counted in the session summary.

Use `Start fresh` in the setup panel to forget the remembered progress for the current profile and folder. When a run reaches the end, the completion message in the focused viewer also offers `Start fresh`, so the same scope can be rebuilt immediately without leaving Quick Sort manually. This makes eligible skipped or copied source files available to review again. Files that were moved out of the source scope remain in their destination folders.

## Optional Qualifiers

Enable `Use qualifiers (optional second key)` to make a two-stage decision. A typical quality setup is:

- `1` = High Quality
- `2` = Medium Quality
- `3` = Low Quality

With qualifiers required, press the qualifier first and the destination second. For example, `1`, then `R`, can route to either `Right Arm/High Quality` or `High Quality/Right Arm`, depending on the selected folder order.

While a qualifier is pending, pressing another configured qualifier replaces it. `Backspace` or `Esc` clears it without leaving the session. Profiles can require a qualifier or send direct destination choices through an `Unclassified` folder.

## Destination and File Handling

Leave `Move to` empty to create key folders relative to the active loaded folder. Choose another parent folder when sorted output should live elsewhere.

The File handling section controls:

- Move or copy mode.
- Append-number, skip, or ask collision behavior.
- Caption and metadata sidecars.
- Whether the session starts in the dedicated fullscreen viewer.

Media and supported sidecars are handled as one bundle. Failed operations do not advance the queue. Undo and redo use the operation journal and refuse unsafe destructive undo when a destination has been replaced externally.

## Focused Viewer Controls

Quick Sort keeps the image central and uses small translucent corner overlays.

- `Fit` displays the whole image in the available viewer.
- `1:1` displays the image at original pixel size.
- Existing mouse-wheel zoom and viewer navigation behavior remain available.
- `Space` skips, `Ctrl + Z` undoes, and `Ctrl + Y` or `Ctrl + Shift + Z` redoes.
- `F11` toggles the dedicated fullscreen viewer.
- `Esc` exits when no qualifier is pending.

Exiting restores the previous TagGUI dock layout, browser filter, media scope, selection, and fullscreen state.
