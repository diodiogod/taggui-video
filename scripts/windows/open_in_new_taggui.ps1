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
$readyFile = Join-Path ([System.IO.Path]::GetTempPath()) (
    'taggui-ready-{0}.signal' -f [Guid]::NewGuid().ToString('N')
)

function Quote-ProcessArgument {
    param([Parameter(Mandatory = $true)][string]$Value)
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Start-TagGUI {
    $argumentLine = @(
        (Quote-ProcessArgument -Value $targetText),
        '--startup-ready-file',
        (Quote-ProcessArgument -Value $readyFile)
    ) -join ' '

    return Start-Process `
        -FilePath $startBat `
        -ArgumentList $argumentLine `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -PassThru
}

try {
    Add-Type -AssemblyName PresentationFramework
    Add-Type -AssemblyName WindowsBase

    $window = New-Object System.Windows.Window
    $window.Title = 'Opening TagGUI'
    $window.Width = 360
    $window.Height = 126
    $window.WindowStartupLocation = 'CenterScreen'
    $window.WindowStyle = 'None'
    $window.ResizeMode = 'NoResize'
    $window.Topmost = $true
    $window.ShowInTaskbar = $false
    $window.Background = [System.Windows.Media.Brushes]::Transparent
    $window.AllowsTransparency = $true

    $border = New-Object System.Windows.Controls.Border
    $border.CornerRadius = New-Object System.Windows.CornerRadius(12)
    $border.BorderThickness = New-Object System.Windows.Thickness(1)
    $border.BorderBrush = New-Object System.Windows.Media.SolidColorBrush(
        [System.Windows.Media.Color]::FromRgb(72, 79, 92)
    )
    $border.Background = New-Object System.Windows.Media.SolidColorBrush(
        [System.Windows.Media.Color]::FromRgb(29, 33, 41)
    )
    $border.Padding = New-Object System.Windows.Thickness(22, 17, 22, 16)

    $panel = New-Object System.Windows.Controls.StackPanel
    $title = New-Object System.Windows.Controls.TextBlock
    $title.Text = 'Opening TagGUI...'
    $title.Foreground = [System.Windows.Media.Brushes]::White
    $title.FontSize = 18
    $title.FontWeight = 'SemiBold'

    $folder = New-Object System.Windows.Controls.TextBlock
    $folderName = Split-Path -Leaf $targetText
    if (-not $folderName) { $folderName = $targetText }
    $folder.Text = "Loading $folderName"
    $folder.Foreground = New-Object System.Windows.Media.SolidColorBrush(
        [System.Windows.Media.Color]::FromRgb(183, 190, 204)
    )
    $folder.FontSize = 12
    $folder.Margin = New-Object System.Windows.Thickness(0, 5, 0, 12)
    $folder.TextTrimming = 'CharacterEllipsis'

    $progress = New-Object System.Windows.Controls.ProgressBar
    $progress.Height = 5
    $progress.IsIndeterminate = $true

    [void]$panel.Children.Add($title)
    [void]$panel.Children.Add($folder)
    [void]$panel.Children.Add($progress)
    $border.Child = $panel
    $window.Content = $border

    $process = Start-TagGUI
    $timer = New-Object System.Windows.Threading.DispatcherTimer
    $timer.Interval = [TimeSpan]::FromMilliseconds(150)
    $state = @{ FailureShownAt = $null }
    $timer.Add_Tick({
        if (Test-Path -LiteralPath $readyFile -PathType Leaf) {
            $timer.Stop()
            $window.Close()
            return
        }
        if ($process.HasExited) {
            if ($null -eq $state.FailureShownAt) {
                $state.FailureShownAt = [DateTime]::UtcNow
                $title.Text = 'TagGUI could not be opened'
                $folder.Text = 'Run TagGUI normally to view startup details.'
                $progress.IsIndeterminate = $false
                $progress.Value = 0
            }
            elseif (([DateTime]::UtcNow - $state.FailureShownAt).TotalSeconds -ge 5) {
                $timer.Stop()
                $window.Close()
            }
        }
    })
    $timer.Start()
    [void]$window.ShowDialog()
}
catch {
    # If desktop feedback is unavailable, preserve the original hidden-launch
    # behavior instead of preventing TagGUI from opening.
    if ($null -eq $process) {
        $process = Start-TagGUI
    }
}
finally {
    if (Test-Path -LiteralPath $readyFile -PathType Leaf) {
        Remove-Item -LiteralPath $readyFile -Force
    }
}

exit 0
