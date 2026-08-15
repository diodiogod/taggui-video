# Quick Tag Review

Quick Tag Review is a focused keyboard workflow for adding ordered, predefined
tags before Auto-Captioner runs.

Configure a shortcut row as `key → tag` in **View > Quick Tags**. Letter and
number keys are available for tag mappings. The profile dropdown includes
General image labeling, Portrait / Character, Clothing / Body parts, Quality
review, and Composition / Shot sizes templates. They use mnemonic keys (`C`
close-up, `K` cowboy shot, `F` full body, `H` high-quality, and more), rather
than arbitrary number sequences. Presets create normal editable profiles; you
can rename, remove, recolor, or remap every row. Control keys remain reserved:

Drag a shortcut row to change the order shown in the review legend and tag
chips. Edit the profile name directly in the profile field and press Enter;
the built-in preset itself stays unchanged.

- `Tab` refines the selected or last pending tag.
- `Shift+Tab` inserts a new tag with autocomplete.
- `Backspace` removes the selected or last pending tag.
- `Enter` confirms inline editing.
- `Space` saves the pending tags to the current image and advances.
- `Ctrl+Z` and `Ctrl+Y` undo and redo image-level tag commits.
- `Escape` exits the review when inline editing is not active.

Tag chips are shown in the order they will be written. Clicking a chip selects
it for refinement or insertion. Text edits are buffered until Enter or Space;
leaving the review does not partially write an unfinished edit.
