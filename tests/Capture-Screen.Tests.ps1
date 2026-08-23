Describe 'Capture-Screen DPI handling' {
    It 'enables per-monitor DPI awareness before reading desktop bounds' {
        $script = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot '..\scripts\windows\Capture-Screen.ps1')

        $script | Should Match 'SetProcessDpiAwarenessContext'
        $script | Should Match 'GetSystemMetrics'
        $script.IndexOf('SetProcessDpiAwarenessContext') | Should BeLessThan $script.IndexOf('GetSystemMetrics')
    }
}
