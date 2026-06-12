$ErrorActionPreference = 'Stop'

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$TargetPath
)

function Resolve-RepoPython {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $candidates = @(
        (Join-Path $RepoRoot 'venv\Scripts\pythonw.exe'),
        (Join-Path $RepoRoot 'venv\Scripts\python.exe'),
        ([System.IO.Path]::GetFullPath((Join-Path $RepoRoot '..\venv\Scripts\pythonw.exe'))),
        ([System.IO.Path]::GetFullPath((Join-Path $RepoRoot '..\venv\Scripts\python.exe')))
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    return $null
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$pythonExe = Resolve-RepoPython -RepoRoot $repoRoot
$helperScript = Join-Path $repoRoot 'taggui\send_open_request.py'
$startBat = Join-Path $repoRoot 'start_windows.bat'

if (-not (Test-Path -LiteralPath $helperScript -PathType Leaf)) {
    throw "Could not find relay helper at '$helperScript'."
}

$targetText = [string]$TargetPath

if ($pythonExe) {
    Push-Location $repoRoot
    try {
        & $pythonExe $helperScript $targetText
        if ($LASTEXITCODE -eq 0) {
            exit 0
        }
    }
    finally {
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath $startBat -PathType Leaf)) {
    exit 1
}

Start-Process -FilePath $startBat -ArgumentList @($targetText) -WorkingDirectory $repoRoot -WindowStyle Hidden
exit 0
