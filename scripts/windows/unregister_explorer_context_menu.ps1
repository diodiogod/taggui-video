$ErrorActionPreference = 'Stop'

$paths = @(
    'HKCU:\Software\Classes\Directory\shell\TagGUI',
    'HKCU:\Software\Classes\Directory\shell\TagGUI.NewWindow',
    'HKCU:\Software\Classes\Directory\Background\shell\TagGUI',
    'HKCU:\Software\Classes\Directory\Background\shell\TagGUI.NewWindow',
    'HKCU:\Software\Classes\Directory\ContextMenus\TagGUI',
    'HKCU:\Software\Classes\Directory\Background\ContextMenus\TagGUI'
)

foreach ($path in $paths) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

Write-Output 'Windows Explorer integration removed.'
