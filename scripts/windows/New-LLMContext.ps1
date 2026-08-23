[CmdletBinding()]
param(
    [datetime]$Date = (Get-Date),
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal')
)

$ErrorActionPreference = 'Stop'
$day = $Date.ToString('yyyy-MM-dd')
$rawPath = Join-Path $JournalRoot "raw\activity-$day.jsonl"
$outputRoot = Join-Path $JournalRoot 'llm-context'
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$outputPath = Join-Path $outputRoot 'latest.md'

if (-not (Test-Path -LiteralPath $rawPath)) {
    Set-Content -LiteralPath $outputPath -Value "# Activity Context`n`nNo local activity events found for $day." -Encoding utf8
    Write-Output $outputPath
    exit 0
}

$events = @(Get-Content -LiteralPath $rawPath | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
$contentPath = Join-Path $JournalRoot "raw\content-$day.jsonl"
$contentEvents = @()
if (Test-Path -LiteralPath $contentPath) { $contentEvents = @(Get-Content -LiteralPath $contentPath | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json }) }
$visualPath = Join-Path $JournalRoot "raw\visual-$day.jsonl"
$visualEvents = @()
if (Test-Path -LiteralPath $visualPath) { $visualEvents = @(Get-Content -LiteralPath $visualPath | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json }) }
$screenshotRoot = Join-Path $JournalRoot "screenshots\$day"
$screenshotCount = if (Test-Path -LiteralPath $screenshotRoot) { @(Get-ChildItem -LiteralPath $screenshotRoot -File -Filter '*.jpg').Count } else { 0 }
$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add('# Activity Context for Jarvis')
$lines.Add('')
$lines.Add("> Date: $day")
$lines.Add('> Source: local metadata collector')
$lines.Add('> Treat observations as evidence; do not claim intent unless explicitly supported.')
$lines.Add('')
$lines.Add('## Observed applications')
$lines.Add('')
$apps = @($events | Where-Object { $_.source -eq 'foreground-window' -and $_.process } | Group-Object process | Sort-Object Count -Descending)
foreach ($app in $apps) { $lines.Add("- $($app.Name): $($app.Count) samples") }
if (-not $apps.Count) { $lines.Add('- None') }
$lines.Add('')
$lines.Add('## Observed project evidence')
$lines.Add('')
$projects = @($events | Where-Object { $_.source -eq 'git-project' })
foreach ($project in $projects) {
    $lines.Add("- Path: $($project.projectPath); branch: $($project.branch); changed files: $($project.changedFileCount); latest commit: $($project.latestCommit) $($project.latestCommitMessage)")
}
if (-not $projects.Count) { $lines.Add('- None') }
$lines.Add('')
$lines.Add('## Captured content')
$lines.Add('')
$lines.Add("- Focused-content events: $($contentEvents.Count)")
$lines.Add("- Full-desktop screenshots: $screenshotCount")
$lines.Add("- Vision-analyzed screenshots: $($visualEvents.Count)")
foreach ($contentEvent in @($contentEvents | Select-Object -Last 12)) {
    $localTime = ([datetime]$contentEvent.localTimestamp).ToString('HH:mm:ss')
    $lines.Add("### $localTime — $($contentEvent.process)")
    $lines.Add('')
    $lines.Add('```text')
    $lines.Add($contentEvent.content)
    $lines.Add('```')
    $lines.Add('')
}
$lines.Add('## Vision observations')
$lines.Add('')
foreach ($visualEvent in @($visualEvents | Select-Object -Last 12)) {
    $analysis = $visualEvent.analysis
    $lines.Add("- $(([datetime]$visualEvent.timestamp).ToLocalTime().ToString('HH:mm')) — $($analysis.activity_type): $($analysis.summary) (confidence: $($analysis.confidence))")
}
if (-not $visualEvents.Count) { $lines.Add('- No vision observations are available yet. Configure a vision endpoint and run the daily summary.') }
$lines.Add('')
$lines.Add('## Recent windows')
$lines.Add('')
foreach ($event in @($events | Where-Object { $_.source -eq 'foreground-window' } | Select-Object -Last 30)) {
    $localTime = ([datetime]$event.localTimestamp).ToString('HH:mm:ss')
    $title = if ($event.windowTitle) { $event.windowTitle } else { '[untitled]' }
    $lines.Add("- $localTime — $($event.process) — $title — active: $($event.active)")
}
Set-Content -LiteralPath $outputPath -Value $lines -Encoding utf8
Write-Output $outputPath


