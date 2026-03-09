# TagGUI Version Bump Instructions

Use the automated script for every release change. Do not edit version strings or the changelog manually.

## Command

```bash
python3 scripts/bump_version_enhanced.py patch "<commit_desc>" "<changelog_desc>"
python3 scripts/bump_version_enhanced.py minor "<commit_desc>" "<changelog_desc>"
python3 scripts/bump_version_enhanced.py major "<commit_desc>" "<changelog_desc>"
```

You can also provide an explicit semantic version instead of `patch`, `minor`, or `major`.

## Rules

- The script reads the current version automatically from `taggui/version.py`.
- The changelog description must be multiline. This is intentional so release notes stay useful.
- Commit description explains implementation details for developers.
- Changelog description explains user-facing impact for release notes.
- The script updates `taggui/version.py`, `README.md`, and `CHANGELOG.md`.
- By default the script stages and commits the version bump. Use `--no-commit` or `--dry-run` when needed.

## Examples

```bash
python3 scripts/bump_version_enhanced.py patch "Tighten compare-drop release handling

Implementation details:
- Stabilize strict-domain release restoration
- Avoid duplicate compare target activation during drag handoff" "Improve compare-drop reliability

- Fix some drag-and-release flows opening the wrong target
- Improve recovery after fast compare handoffs
- Better stability when moving between floating viewers"
```

```bash
python3 scripts/bump_version_enhanced.py minor "Add release metadata baseline

Implementation details:
- Add canonical TagGUI version module
- Add automated bump script and changelog updater" "Add automated release versioning

- README now shows the current TagGUI release version
- Releases now get structured changelog entries automatically
- App metadata now exposes the current version at runtime"
```

## Dry Run

```bash
python3 scripts/bump_version_enhanced.py patch "Preview release tooling" "Preview release tooling

- Check which files would be updated
- Preview the generated changelog entry" --dry-run
```
