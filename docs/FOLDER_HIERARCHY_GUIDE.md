# Folder Hierarchy Guide

Open **View > Folders** or choose the **Folder Management** workspace to show a
snapshot of the loaded folder hierarchy. The tree shows the recursive media
count for each folder.

## Navigation and Quick Sort

- Double-click a folder to open it in the active browser.
- Select a folder and choose **Use selected folder for Quick Sort** to open it
  and prepare Quick Sort with **Current folder** scope.
- Click **Refresh**, or press `F5` while the panel is focused, after making
  changes in Windows Explorer.

The panel intentionally does not monitor the filesystem continuously.

## Folder operations

Use the buttons or the folder context menu to create, rename, move, or delete
folders. Rename and move are restricted to the loaded hierarchy and update the
TagGUI index without replacing image IDs. The first implementation deletes only
empty folders so deletion can be safely undone.

Folder operations participate in TagGUI's standard **Edit > Undo** and
**Edit > Redo** history. Undo can refuse an operation if later filesystem
changes would make it unsafe, such as adding files to a newly created folder.
