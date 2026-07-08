param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$TargetPath
)

$ErrorActionPreference = 'Stop'

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$startBat = Join-Path $repoRoot 'start_windows.bat'

if (-not (Test-Path -LiteralPath $startBat -PathType Leaf)) {
    throw "Could not find launcher at '$startBat'."
}

$targetText = [string]$TargetPath

Start-Process `
    -FilePath $startBat `
    -ArgumentList @($targetText) `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden

exit 0
