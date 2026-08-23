[CmdletBinding()]
param(
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal')
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath (Join-Path $JournalRoot 'config\settings.json') | ConvertFrom-Json
$cutoff = (Get-Date).AddDays(-[int]$config.retentionDays)
foreach ($relativePath in @('raw', 'screenshots', 'hourly', 'daily', 'llm-context')) {
    $target = Join-Path $JournalRoot $relativePath
    if (-not (Test-Path -LiteralPath $target)) { continue }
    Get-ChildItem -LiteralPath $target -File -Recurse | Where-Object LastWriteTime -lt $cutoff | Remove-Item -Force
}


