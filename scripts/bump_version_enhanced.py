#!/usr/bin/env python3
"""Bump the TagGUI version, update changelog, and optionally commit."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

from version_utils import VersionManager


def run_git_command(command: list[str], *, cwd: str) -> bool:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    except OSError as exc:
        print(f"Error running git command {' '.join(command)}: {exc}")
        return False
    if result.returncode != 0:
        print(f"Git command failed: {' '.join(command)}")
        if result.stderr:
            print(result.stderr.strip())
        return False
    return True


def resolve_target_version(current_version: str, requested: str) -> str:
    if requested.lower() not in {"patch", "minor", "major"}:
        return requested

    major, minor, patch = map(int, current_version.split("."))
    if requested.lower() == "patch":
        patch += 1
    elif requested.lower() == "minor":
        minor += 1
        patch = 0
    else:
        major += 1
        minor = 0
        patch = 0
    return f"{major}.{minor}.{patch}"


def ensure_version_increases(current_version: str, new_version: str) -> bool:
    return tuple(map(int, new_version.split("."))) > tuple(map(int, current_version.split(".")))


def build_commit_message(version: str, description: str) -> str:
    title = f"Version {version}"
    if "\n" in description:
        return f"{title}\n\n{description}"
    return f"{title}: {description}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bump TagGUI version with separate commit and changelog descriptions."
    )
    parser.add_argument(
        "version",
        help="New version or auto-increment selector: patch, minor, major",
    )
    parser.add_argument(
        "commit_description",
        nargs="?",
        help="Commit message body describing the implementation details",
    )
    parser.add_argument(
        "changelog_description",
        nargs="?",
        help="Authored Markdown changelog body with explicit category headings",
    )
    parser.add_argument("--commit-file", help="Read commit description from a UTF-8 file")
    parser.add_argument("--changelog-file", help="Read authored Markdown changelog body from a UTF-8 file")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes only")
    parser.add_argument("--no-commit", action="store_true", help="Skip git commit")
    parser.add_argument(
        "--allow-downgrade",
        action="store_true",
        help="Allow setting a non-increasing version",
    )
    args = parser.parse_args()

    if args.commit_file or args.changelog_file:
        if not (args.commit_file and args.changelog_file):
            parser.error("Use --commit-file and --changelog-file together")
        if args.commit_description is not None or args.changelog_description is not None:
            parser.error("Use either positional descriptions or file inputs, not both")
        try:
            with open(args.commit_file, encoding="utf-8-sig") as handle:
                commit_description = handle.read().strip()
            with open(args.changelog_file, encoding="utf-8-sig") as handle:
                changelog_description = handle.read().strip()
        except (OSError, UnicodeError) as exc:
            parser.error(f"Cannot read release descriptions: {exc}")
    else:
        if not args.commit_description or not args.changelog_description:
            parser.error("Provide both commit and changelog descriptions, or both file inputs")
        commit_description = args.commit_description.replace("\\n", "\n").strip()
        changelog_description = args.changelog_description.replace("\\n", "\n").strip()

    version_manager = VersionManager()
    current_version = version_manager.get_current_version()
    if not current_version:
        print("Error: Could not determine the current TagGUI version")
        return 1

    new_version = resolve_target_version(current_version, args.version)
    if not version_manager.validate_version(new_version):
        print(f"Error: Invalid version format '{new_version}'")
        return 1

    if not args.allow_downgrade and not ensure_version_increases(current_version, new_version):
        print(
            f"Error: New version {new_version} must be greater than current version {current_version}"
        )
        return 1

    try:
        changelog_preview = version_manager.preview_changelog_entry(new_version, changelog_description)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Current version: {current_version}")
    print(f"New version: {new_version}")
    print("\nCommit description:")
    print("=" * 50)
    print(commit_description)
    print("=" * 50)
    print("\nChangelog description:")
    print("=" * 50)
    print(changelog_description)
    print("=" * 50)

    if args.dry_run:
        print("\n[DRY RUN] Files that would be updated:")
        for relative_path in list(version_manager.version_files) + ["CHANGELOG.md"]:
            full_path = os.path.join(version_manager.project_root, relative_path)
            marker = "OK" if os.path.exists(full_path) else "MISSING"
            print(f"- {marker} {relative_path}")
        print("\n[DRY RUN] Changelog preview:")
        print("=" * 50)
        print(changelog_preview.rstrip())
        print("=" * 50)
        if not args.no_commit:
            print("[DRY RUN] A git commit would be created.")
        return 0

    backup = version_manager.backup_files()
    try:
        if not version_manager.update_all_versions(new_version):
            raise RuntimeError("Failed to update version files")
        if not version_manager.add_changelog_entry(new_version, changelog_description):
            raise RuntimeError("Failed to update changelog")

        if not args.no_commit:
            if not os.path.exists(os.path.join(version_manager.project_root, ".git")):
                print("Warning: Not in a git repository, skipping commit")
                return 0

            if not run_git_command(["git", "add", "-A"], cwd=version_manager.project_root):
                raise RuntimeError("Failed to stage version bump changes")

            diff_result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=version_manager.project_root,
            )
            if diff_result.returncode == 0:
                print("No staged changes detected")
                return 0

            commit_message = build_commit_message(new_version, commit_description)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as handle:
                handle.write(commit_message)
                temp_path = handle.name
            try:
                if not run_git_command(
                    ["git", "commit", "-F", temp_path],
                    cwd=version_manager.project_root,
                ):
                    raise RuntimeError("Failed to create git commit")
            finally:
                os.unlink(temp_path)

        print(f"Successfully bumped TagGUI to v{new_version}")
        return 0
    except Exception as exc:
        print(str(exc))
        print("Restoring files from backup...")
        version_manager.restore_files(backup)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
