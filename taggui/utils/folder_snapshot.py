"""Filesystem-only hierarchy snapshots for the folder panel."""
import os
from pathlib import Path


def collect_folder_snapshot(payload, cancelled):
    root, suffixes, excluded = payload
    root = Path(root)
    rows = []
    stack = [(root,None)]
    while stack:
        if cancelled.is_set():
            return None
        path, parent = stack.pop()
        count, children, unavailable = 0, [], False
        try:
            with os.scandir(path) as entries:
                for position, entry in enumerate(entries):
                    if position % 128 == 0 and cancelled.is_set():
                        return None
                    if entry.name in excluded:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        children.append(Path(entry.path))
                    elif (Path(entry.name).suffix.lower() in suffixes
                          and (entry.is_file(follow_symlinks=False) or entry.is_symlink())):
                        count += 1
        except OSError:
            unavailable = True
        index = len(rows)
        rows.append([path,parent,count,unavailable])
        stack.extend((child,index) for child in
                     reversed(sorted(children,key=lambda value:value.name.casefold())))
    for _, parent, count, _ in reversed(rows):
        if parent is not None:
            rows[parent][2] += count
    return tuple(tuple(row) for row in rows)
