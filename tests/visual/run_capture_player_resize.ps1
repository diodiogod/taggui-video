param(
    [switch]$Offscreen,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonExe = Join-Path $repoRoot "venv\Scripts\python.exe"
$scriptPath = Join-Path $repoRoot "tests\visual\capture_player_resize.py"

if (-not (Test-Path $pythonExe)) {
    Write-Error "Python executable not found in venv: $pythonExe"
    exit 1
}

if (-not (Test-Path $scriptPath)) {
    Write-Error "Capture script not found: $scriptPath"
    exit 1
}

if ($Offscreen) {
    & $pythonExe $scriptPath --offscreen @ExtraArgs
} else {
    & $pythonExe $scriptPath @ExtraArgs
}
exit $LASTEXITCODE
