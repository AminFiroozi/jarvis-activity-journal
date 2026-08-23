[CmdletBinding()]
param(
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal')
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath (Join-Path $JournalRoot 'config\settings.json') | ConvertFrom-Json
$rawRoot = Join-Path $JournalRoot 'raw'
New-Item -ItemType Directory -Force -Path $rawRoot | Out-Null
$now = Get-Date
$outputPath = Join-Path $rawRoot ("activity-{0}.jsonl" -f $now.ToString('yyyy-MM-dd'))

foreach ($configuredPath in @($config.projectPaths)) {
    if (-not (Test-Path -LiteralPath $configuredPath -PathType Container)) { continue }
    $gitPath = Join-Path $configuredPath '.git'
    if (-not (Test-Path -LiteralPath $gitPath)) { continue }

    $branch = (& git -C $configuredPath branch --show-current 2>$null | Select-Object -First 1).Trim()
    $statusLines = @(& git -C $configuredPath status --porcelain 2>$null)
    $latest = (& git -C $configuredPath log -1 --format='%h|%s|%aI' 2>$null | Select-Object -First 1).Trim()
    $latestParts = $latest -split '\|', 3
    $event = [ordered]@{
        timestamp = $now.ToUniversalTime().ToString('o')
        localTimestamp = $now.ToString('o')
        source = 'git-project'
        projectPath = (Resolve-Path -LiteralPath $configuredPath).Path
        branch = $branch
        changedFileCount = $statusLines.Count
        latestCommit = if ($latestParts.Count -gt 0) { $latestParts[0] } else { $null }
        latestCommitMessage = if ($latestParts.Count -gt 1) { $latestParts[1] } else { $null }
        latestCommitTimestamp = if ($latestParts.Count -gt 2) { $latestParts[2] } else { $null }
    }
    ($event | ConvertTo-Json -Compress -Depth 5) | Add-Content -LiteralPath $outputPath -Encoding utf8
}


