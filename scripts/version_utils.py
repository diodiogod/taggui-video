#!/usr/bin/env python3
"""Version management helpers for TagGUI."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, List, Optional


class VersionManager:
    """Manage version updates across the repository."""

    def __init__(self, project_root: str | None = None) -> None:
        self.project_root = project_root or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        self.version_files = {
            "README.md": {
                "replacements": [
                    {
                        "pattern": r"# TagGUI Video 1M v(\d+\.\d+\.\d+)",
                        "template": "# TagGUI Video 1M v{version}",
                    },
                    {
                        "pattern": r"https://img\.shields\.io/badge/version-\d+\.\d+\.\d+-",
                        "template": "https://img.shields.io/badge/version-{version}-",
                    },
                ],
            },
            "taggui/version.py": {
                "replacements": [
                    {
                        "pattern": r'__version__ = "(\d+\.\d+\.\d+)"',
                        "template": '__version__ = "{version}"',
                    }
                ],
            },
        }

    def validate_version(self, version: str) -> bool:
        return bool(re.fullmatch(r"\d+\.\d+\.\d+", version))

    def get_current_version(self) -> Optional[str]:
        version_file = os.path.join(self.project_root, "taggui", "version.py")
        try:
            with open(version_file, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError as exc:
            print(f"Error reading current version: {exc}")
            return None

        match = re.search(
            self.version_files["taggui/version.py"]["replacements"][0]["pattern"],
            content,
        )
        return match.group(1) if match else None

    def update_version_in_file(self, file_path: str, version: str) -> bool:
        relative_path = os.path.relpath(file_path, self.project_root)
        config = self.version_files.get(relative_path)
        if config is None:
            print(f"Warning: {relative_path} is not configured for version updates")
            return False

        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                content = handle.read()
            new_content = content
            replaced_any = False
            for replacement in config["replacements"]:
                updated_content = re.sub(
                    replacement["pattern"],
                    replacement["template"].format(version=version),
                    new_content,
                )
                if updated_content != new_content:
                    replaced_any = True
                new_content = updated_content
            if not replaced_any:
                print(f"Warning: No version string found in {relative_path}")
                return False
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(new_content)
            print(f"Updated {relative_path}")
            return True
        except OSError as exc:
            print(f"Error updating {relative_path}: {exc}")
            return False

    def update_all_versions(self, version: str) -> bool:
        if not self.validate_version(version):
            print(f"Error: Invalid version format '{version}'")
            return False

        success = True
        for relative_path in self.version_files:
            full_path = os.path.join(self.project_root, relative_path)
            if not os.path.exists(full_path):
                print(f"Warning: {relative_path} not found")
                success = False
                continue
            if not self.update_version_in_file(full_path, version):
                success = False
        return success

    def _has_whole_word(self, text: str, words: List[str]) -> bool:
        return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)

    def _categorize_line(self, line: str) -> str:
        text = line.lower()
        if self._has_whole_word(
            text,
            [
                "fix",
                "bug",
                "error",
                "issue",
                "resolve",
                "correct",
                "crash",
                "problem",
                "broken",
                "regression",
            ],
        ):
            return "Fixed"
        if self._has_whole_word(
            text,
            ["remove", "delete", "deprecate", "drop", "eliminate"],
        ):
            return "Removed"
        if self._has_whole_word(
            text,
            [
                "improve",
                "enhance",
                "optimize",
                "update",
                "change",
                "refactor",
                "performance",
                "better",
                "faster",
            ],
        ):
            return "Changed"
        return "Added"

    def _generate_changelog_entry(self, version: str, description: str) -> str:
        lines = [line.strip() for line in description.splitlines() if line.strip()]
        if len(lines) < 2:
            raise ValueError(
                "Changelog descriptions must be multiline so release notes stay useful."
            )

        sections: Dict[str, List[str]] = {
            "Added": [],
            "Changed": [],
            "Fixed": [],
            "Removed": [],
        }
        for raw_line in lines:
            cleaned = re.sub(r"^[-*•]\s*", "", raw_line)
            if not cleaned:
                continue
            sections[self._categorize_line(cleaned)].append(cleaned)

        today = datetime.now().strftime("%Y-%m-%d")
        entry_lines = [f"## [{version}] - {today}"]
        for heading in ("Added", "Changed", "Fixed", "Removed"):
            items = sections[heading]
            if not items:
                continue
            entry_lines.extend(["", f"### {heading}", ""])
            entry_lines.extend(f"- {item}" for item in items)
        entry_lines.append("")
        return "\n".join(entry_lines)

    def preview_changelog_entry(self, version: str, description: str) -> str:
        return self._generate_changelog_entry(version, description)

    def add_changelog_entry(self, version: str, description: str) -> bool:
        changelog_path = os.path.join(self.project_root, "CHANGELOG.md")
        try:
            with open(changelog_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError as exc:
            print(f"Error reading changelog: {exc}")
            return False

        try:
            new_entry = self._generate_changelog_entry(version, description).rstrip()
        except ValueError as exc:
            print(str(exc))
            return False

        lines = content.splitlines()
        insert_index = next(
            (index for index, line in enumerate(lines) if line.startswith("## [")),
            len(lines),
        )
        if insert_index > 0 and lines[insert_index - 1] != "":
            lines.insert(insert_index, "")
            insert_index += 1
        lines.insert(insert_index, new_entry)
        updated_content = "\n".join(lines).rstrip() + "\n"

        try:
            with open(changelog_path, "w", encoding="utf-8") as handle:
                handle.write(updated_content)
            print(f"Updated CHANGELOG.md for v{version}")
            return True
        except OSError as exc:
            print(f"Error writing changelog: {exc}")
            return False

    def backup_files(self) -> Dict[str, str]:
        backups: Dict[str, str] = {}
        tracked_files = list(self.version_files) + ["CHANGELOG.md"]
        for relative_path in tracked_files:
            full_path = os.path.join(self.project_root, relative_path)
            if not os.path.exists(full_path):
                continue
            with open(full_path, "r", encoding="utf-8") as handle:
                backups[relative_path] = handle.read()
        return backups

    def restore_files(self, backups: Dict[str, str]) -> bool:
        try:
            for relative_path, content in backups.items():
                full_path = os.path.join(self.project_root, relative_path)
                with open(full_path, "w", encoding="utf-8") as handle:
                    handle.write(content)
            return True
        except OSError as exc:
            print(f"Error restoring files: {exc}")
            return False
