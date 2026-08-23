[CmdletBinding()]
param(
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal')
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath (Join-Path $JournalRoot 'config\settings.json') | ConvertFrom-Json
if (-not $config.contentCapture.enabled) { exit 0 }
Add-Type -AssemblyName System.Drawing, System.Windows.Forms

# Windows may expose logical coordinates when display scaling is enabled.
# Opt into per-monitor DPI awareness before reading the desktop rectangle so
# the bitmap matches the physical pixels on every monitor.
if (-not ('Jarvis.ScreenCapture.NativeMethods' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace Jarvis.ScreenCapture {
    public static class NativeMethods {
        [DllImport("user32.dll", SetLastError = true)]
        public static extern bool SetProcessDpiAwarenessContext(IntPtr dpiContext);

        [DllImport("user32.dll")]
        public static extern int GetSystemMetrics(int index);
    }
}
'@
}
[void][Jarvis.ScreenCapture.NativeMethods]::SetProcessDpiAwarenessContext([IntPtr](-4))

$now = Get-Date
$directory = Join-Path $JournalRoot ("screenshots\{0}" -f $now.ToString('yyyy-MM-dd'))
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$bounds = [pscustomobject]@{
    Left = [Jarvis.ScreenCapture.NativeMethods]::GetSystemMetrics(76)
    Top = [Jarvis.ScreenCapture.NativeMethods]::GetSystemMetrics(77)
    Width = [Jarvis.ScreenCapture.NativeMethods]::GetSystemMetrics(78)
    Height = [Jarvis.ScreenCapture.NativeMethods]::GetSystemMetrics(79)
}
$bounds | Add-Member -NotePropertyName Right -NotePropertyValue ($bounds.Left + $bounds.Width)
$bounds | Add-Member -NotePropertyName Bottom -NotePropertyValue ($bounds.Top + $bounds.Height)
$bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {
    $graphics.CopyFromScreen($bounds.Left, $bounds.Top, 0, 0, $bitmap.Size)
    $path = Join-Path $directory ("screen-{0}.jpg" -f $now.ToString('HH-mm-ss-fff'))
    $encoder = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object MimeType -eq 'image/jpeg'
    $parameters = New-Object System.Drawing.Imaging.EncoderParameters(1)
    $parameters.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [long]60)
    $bitmap.Save($path, $encoder, $parameters)
    Write-Output $path
}
finally {
    $graphics.Dispose()
    $bitmap.Dispose()
}

