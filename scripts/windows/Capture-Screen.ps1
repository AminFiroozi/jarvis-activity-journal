[CmdletBinding()]
param(
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal')
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath (Join-Path $JournalRoot 'config\settings.json') | ConvertFrom-Json
if (-not $config.contentCapture.enabled) { exit 0 }
Add-Type -AssemblyName System.Drawing, System.Windows.Forms

$now = Get-Date
$directory = Join-Path $JournalRoot ("screenshots\{0}" -f $now.ToString('yyyy-MM-dd'))
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
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


