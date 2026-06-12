$ErrorActionPreference = 'Stop'

function Ensure-RegistryKey {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -Path $Path -Force | Out-Null
    }
}

function Set-RegistryStringValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )

    Ensure-RegistryKey -Path $Path
    New-ItemProperty -Path $Path -Name $Name -Value $Value -PropertyType String -Force | Out-Null
}

function Set-RegistryDefaultValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )

    Ensure-RegistryKey -Path $Path
    Set-Item -Path $Path -Value $Value -Force
}

function Register-DirectCommand {
    param(
        [Parameter(Mandatory = $true)][string]$VerbKey,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$IconPath
    )

    $commandKey = Join-Path $VerbKey 'command'
    Set-RegistryDefaultValue -Path $VerbKey -Value $Label
    Set-RegistryStringValue -Path $VerbKey -Name 'MUIVerb' -Value $Label
    Set-RegistryStringValue -Path $VerbKey -Name 'Icon' -Value $IconPath
    Set-RegistryDefaultValue -Path $commandKey -Value $Command
}

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

    throw "Could not find a Python executable in this TagGUI environment."
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$startBat = Join-Path $repoRoot 'start_windows.bat'
$pythonExe = Resolve-RepoPython -RepoRoot $repoRoot
$sendScript = Join-Path $repoRoot 'taggui\send_open_request.py'
$iconPath = Join-Path $repoRoot 'images\icon.ico'

if (-not (Test-Path -LiteralPath $startBat -PathType Leaf)) {
    throw "Could not find start_windows.bat at '$startBat'."
}
if (-not (Test-Path -LiteralPath $sendScript -PathType Leaf)) {
    throw "Could not find current-window helper at '$sendScript'."
}
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    $iconPath = $startBat
}

$folderCurrentKey = 'HKCU:\Software\Classes\Directory\shell\TagGUI'
$folderNewKey = 'HKCU:\Software\Classes\Directory\shell\TagGUI.NewWindow'
$backgroundCurrentKey = 'HKCU:\Software\Classes\Directory\Background\shell\TagGUI'
$backgroundNewKey = 'HKCU:\Software\Classes\Directory\Background\shell\TagGUI.NewWindow'

$folderCurrentCommand = '"{0}" "{1}" "%1"' -f $pythonExe, $sendScript
$folderNewCommand = 'cmd.exe /c "cd /d ""{0}"" && call ""{1}"" ""%1"""' -f $repoRoot, $startBat
$backgroundCurrentCommand = '"{0}" "{1}" "%V"' -f $pythonExe, $sendScript
$backgroundNewCommand = 'cmd.exe /c "cd /d ""{0}"" && call ""{1}"" ""%V"""' -f $repoRoot, $startBat

Register-DirectCommand `
    -VerbKey $folderCurrentKey `
    -Label 'Open in TagGUI' `
    -Command $folderCurrentCommand `
    -IconPath $iconPath

Register-DirectCommand `
    -VerbKey $folderNewKey `
    -Label 'Open in New TagGUI Window' `
    -Command $folderNewCommand `
    -IconPath $iconPath

Register-DirectCommand `
    -VerbKey $backgroundCurrentKey `
    -Label 'Open in TagGUI' `
    -Command $backgroundCurrentCommand `
    -IconPath $iconPath

Register-DirectCommand `
    -VerbKey $backgroundNewKey `
    -Label 'Open in New TagGUI Window' `
    -Command $backgroundNewCommand `
    -IconPath $iconPath

Write-Output 'Windows Explorer integration installed.'
