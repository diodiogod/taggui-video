# TagGUI Version Bump Instructions

Use the script for version files and changelog insertion. The agent writes and
categorizes the release notes; the script preserves the authored Markdown.

## Release preparation

- Follow the shared `bump-version` skill: delegate changelog drafting to Luna when available, then review the proposed entry.
- The commit description and changelog must cover all relevant changes since the previous version bump, not just the latest commit. Inspect commit bodies and relevant diffs.
- Consolidate related changes and explain the net user-facing result. Omit duplicate entries and temporary development problems fixed before release.
- Follow `AGENTS.md`: commit substantial changes only after the user confirms they work; never push without an explicit request.
- The script reads the current version from `taggui/version.py`. Use `patch`, `minor`, `major`, or an explicit `X.Y.Z`; do not manually edit version strings.

## Recommended command: UTF-8 file inputs

Write a separate developer-focused commit description and reviewed changelog body to UTF-8 files outside the repository.

```bash
python3 scripts/bump_version_enhanced.py patch --commit-file /tmp/taggui-release-commit.txt --changelog-file /tmp/taggui-release-notes.md --dry-run
```

On Windows, use the project's Python environment and temporary files, for example:

```powershell
$releaseCommitFile = Join-Path $env:TEMP 'taggui-release-commit.txt'
$releaseNotesFile = Join-Path $env:TEMP 'taggui-release-notes.md'

& '.\venv\Scripts\python.exe' 'scripts\bump_version_enhanced.py' patch --commit-file $releaseCommitFile --changelog-file $releaseNotesFile --dry-run
```

Inspect the preview, then remove `--dry-run` for the authorized release. Use `--no-commit` when only file updates are intended. Provide both file options together; do not mix them with positional descriptions.

## Changelog body format

Supply explicit level-three Markdown categories, without the version/date header:

```markdown
### Fixed

- Floating viewers now activate the intended comparison target after a drag-and-release action.
  - Fast handoffs between viewers retain the selected target.

### Changed

- Comparison controls explain how dragging between floating viewers works.
```

Supported headings are `### Added`, `### Changed`, `### Deprecated`, `### Removed`, `### Fixed`, and `### Security`.

- Choose categories by meaning, not keywords. Removing an erroneous warning can be a fix; deleting internal code does not necessarily remove a user feature.
- Keep related explanations together. The script preserves category order, paragraphs, formatting, nested bullets, and literal backslashes in file inputs.
- Omit empty sections. One section with one bullet is sufficient for a small release.
- The script supplies the `## [version] - date` header and spacing, and trims surrounding whitespace.
- Unstructured descriptions, unsupported headings, and empty sections fail before any version files change. There is no automatic categorization fallback.

Actual multiline positional descriptions are also supported:

```bash
python3 scripts/bump_version_enhanced.py patch "Tighten compare-drop release handling

- Stabilize release restoration and target activation" "### Fixed

- Floating viewers now activate the intended comparison target after dragging." --dry-run
```

## Commit description

Use a clear title and normally a multiline developer-focused body. Never add AI co-author credits or generated-by footers. Use issue-closing keywords only after the user confirms the fix works; otherwise use neutral issue references.

## Script behavior

- Updates `taggui/version.py`, `README.md`, and `CHANGELOG.md`.
- Preserves the reviewed changelog body and adds the version/date header.
- By default stages all changes with `git add -A` and creates a version-bump commit. Inspect the working tree first and resolve unrelated edits before allowing that commit. Do not discard or stash other work automatically.
- `--dry-run` previews without writing or committing; invalid notes return an error.
- `--no-commit` updates files without staging or committing.
- `--allow-downgrade` permits a non-increasing version for an explicitly intended correction.

If multiline quoting is troublesome, use the paired UTF-8 file options. If changelog validation fails, supply a supported `###` category with content in every section, without a free-text title or release header.
