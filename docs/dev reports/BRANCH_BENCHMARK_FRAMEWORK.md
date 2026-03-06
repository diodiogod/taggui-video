# Branch Benchmark Framework

This is the reusable setup for comparing TagGUI branches without DB/cache contamination.

## Scope

- Branches:
  - `old main` -> `J:\Aitools\MyTagGUI\taggui_old_main`
  - `olde 1m-images-pagination` -> `J:\Aitools\MyTagGUI\taggui_olde_1m_images_pagination`
  - `current` -> `J:\Aitools\MyTagGUI\taggui_working`
- Shared Python:
  - `J:\Aitools\MyTagGUI\taggui_working\venv\Scripts\python.exe`
- Datasets:
  - `1m` -> `J:\Aitools\MyTagGUI\taggui_working\test-1m-images`
  - `20k` -> `G:\Downloads\zDowp\AZ All\AZ All` (recursive DB mode)
  - `300` -> `K:\Fotos\Wallpapers\rodar`
  - `video` -> `J:\test`

## Why this exists

- TagGUI stores per-folder DB as `.taggui_index.db`.
- Global settings are shared across branches.
- If DB/cache are not isolated, comparisons become invalid.

The helper script isolates:

- DB snapshots per profile (`old main`, `olde 1m-images-pagination`, `current`)
- Thumbnail cache per profile

Storage root:

- `C:\Users\<you>\.taggui_benchmark_profiles\...`

## Tools

- Core helper:
  - `tools/taggui_profile_switch.py`
- PowerShell wrapper:
  - `tools/benchmark_profile.ps1`

## Minimal workflow

1. Close all TagGUI windows.
2. Activate profile for dataset.
3. Launch the target branch.
4. Test.
5. Capture profile snapshot.

## PowerShell quick commands

From `J:\Aitools\MyTagGUI\taggui_working`:

```powershell
# Activate profile before testing
.\tools\benchmark_profile.ps1 activate current 300
.\tools\benchmark_profile.ps1 activate "old main" 20k
.\tools\benchmark_profile.ps1 activate "olde 1m-images-pagination" 1m

# Status
.\tools\benchmark_profile.ps1 status current 20k

# Capture after testing
.\tools\benchmark_profile.ps1 capture current 300
```

Notes:

- Dataset key `20k` automatically uses recursive DB handling.
- Profile names with spaces must be quoted.

## Branch launch commands

```powershell
# current
cd J:\Aitools\MyTagGUI\taggui_working
J:\Aitools\MyTagGUI\taggui_working\venv\Scripts\python.exe taggui\run_gui.py

# old main
cd J:\Aitools\MyTagGUI\taggui_old_main
J:\Aitools\MyTagGUI\taggui_working\venv\Scripts\python.exe taggui\run_gui.py

# olde 1m-images-pagination
cd J:\Aitools\MyTagGUI\taggui_olde_1m_images_pagination
J:\Aitools\MyTagGUI\taggui_working\venv\Scripts\python.exe taggui\run_gui.py
```

## Known rules for fair comparison

1. Compare only features present in all tested branches.
2. Run cold and warm where relevant.
3. Keep strategy explicit:
   - current path: `windowed_strict`
   - legacy paths: mark as `default` when strategy option does not exist
4. Do not store benchmark cache inside dataset folders.

## Troubleshooting

### `PermissionError [WinError 32] ... .taggui_index.db`

Cause: TagGUI still running and holding DB file.

Fix:

1. Close all TagGUI windows/processes.
2. Re-run activate command.

### No profile snapshot exists

Expected on first run. Activate creates clean state; after testing, run `capture`.

### Need to inspect profile storage

Use status command and read:

- `Profile store: ...`
- `Profiles: ...`

