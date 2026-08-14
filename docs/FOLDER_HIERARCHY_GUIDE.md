# Folder Hierarchy Guide

Open **View > Folders** or choose the **Folder Management** workspace to show a
snapshot of the loaded folder hierarchy. The tree shows the recursive media
count for each folder.

## Navigation and Quick Sort

- Double-click a folder to open it in the active browser.
- Click **↑** to reveal the current root's parent while keeping the loaded
  folder selected. This navigates the tree without loading another dataset.
- Select a folder and choose **Use selected folder for Quick Sort** to open it
  and prepare Quick Sort with **Current folder** scope.
- Click **Refresh**, or press `F5` while the panel is focused, after making
  changes in Windows Explorer. Refresh and **Up** recalculate media totals for
  every displayed folder, including siblings that are not loaded as datasets.

The panel intentionally does not monitor the filesystem continuously.

When **Folders** is docked immediately to the left of **Images**, a narrow
handle appears on the left edge of Images. Click it to collapse the Folders
panel and click it again to restore the previous width. The folder toolbar also
compacts automatically at narrow widths; all commands remain available from the
tree's context menu.

## Folder operations

Use the buttons or the folder context menu to create, rename, move, or delete
folders. Rename and move are restricted to the loaded hierarchy and update the
TagGUI index without replacing image IDs. The first implementation deletes only
empty folders so deletion can be safely undone.

The currently loaded root can also be renamed. TagGUI releases its active index,
renames the directory, reopens the new path, and restores the selected media.
Press `F2` to rename the selected folder, matching the standard file-browser
shortcut.

You can also drag a folder onto another folder to move it there. Folders remain
alphabetically ordered after refresh; dragging changes their parent rather than
creating a separate cosmetic order. The **Move** button remains available when
choosing a distant destination is more convenient than dragging through the
tree.

Folder operations participate in TagGUI's standard **Edit > Undo** and
**Edit > Redo** history. Undo can refuse an operation if later filesystem
changes would make it unsafe, such as adding files to a newly created folder.
