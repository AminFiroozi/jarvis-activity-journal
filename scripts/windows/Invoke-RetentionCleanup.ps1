[CmdletBinding()]
param(
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal')
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath (Join-Path $JournalRoot 'config\settings.json') | ConvertFrom-Json
$retentionDays = if ($null -ne $config.privacy -and $null -ne $config.privacy.retentionDays) { [int]$config.privacy.retentionDays } else { [int]$config.retentionDays }
$cutoff = (Get-Date).AddDays(-$retentionDays)
$removed = 0
foreach ($relativePath in @('raw', 'screenshots', 'hourly', 'daily', 'llm-context')) {
    $target = Join-Path $JournalRoot $relativePath
    if (-not (Test-Path -LiteralPath $target)) { continue }
    $oldFiles = @(Get-ChildItem -LiteralPath $target -File -Recurse | Where-Object LastWriteTime -lt $cutoff)
    foreach ($file in $oldFiles) { Remove-Item -LiteralPath $file.FullName -Force; $removed++ }
}
Write-Output ([ordered]@{ retentionDays = $retentionDays; cutoff = $cutoff.ToUniversalTime().ToString('o'); removedFiles = $removed } | ConvertTo-Json -Compress)

