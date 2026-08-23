[CmdletBinding()]
param(
    [datetime]$Date = (Get-Date),
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal'),
    [switch]$Hourly
)

$ErrorActionPreference = 'Stop'
$cleanup = Join-Path $PSScriptRoot 'Invoke-RetentionCleanup.ps1'
if (Test-Path -LiteralPath $cleanup) { & $cleanup }
$analyzer = Join-Path $PSScriptRoot 'Analyze-Screenshots.ps1'
if (Test-Path -LiteralPath $analyzer) { try { & $analyzer | Out-Null } catch { Write-Warning "Screenshot analysis skipped: $($_.Exception.Message)" } }
$day = $Date.ToString('yyyy-MM-dd')
$rawPath = Join-Path $JournalRoot "raw\activity-$day.jsonl"
if (-not (Test-Path -LiteralPath $rawPath)) { Write-Output "No events found for $day"; exit 0 }
$events = @(Get-Content -LiteralPath $rawPath | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
$summaryRoot = if ($Hourly) { Join-Path $JournalRoot 'hourly' } else { Join-Path $JournalRoot 'daily' }
New-Item -ItemType Directory -Force -Path $summaryRoot | Out-Null
$outputName = if ($Hourly) { "$day-$((Get-Date).ToString('HH')).md" } else { "$day.md" }
$outputPath = Join-Path $summaryRoot $outputName

$windowEvents = @($events | Where-Object { $_.source -eq 'foreground-window' -and $_.process })
$activeEvents = @($windowEvents | Where-Object { $_.active -eq $true })
$appRows = @($activeEvents | Group-Object process | Sort-Object Count -Descending | ForEach-Object {
    [pscustomobject]@{ App = $_.Name; Samples = $_.Count; Minutes = [math]::Round($_.Count / 60, 1) }
})
$projectEvents = @($events | Where-Object { $_.source -eq 'git-project' })
$first = if ($events.Count) { ([datetime]$events[0].localTimestamp).ToString('HH:mm') } else { '-' }
$last = if ($events.Count) { ([datetime]$events[-1].localTimestamp).ToString('HH:mm') } else { '-' }

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# Automatic Activity Journal — $day")
$lines.Add('')
$lines.Add('> Generated from local metadata. This records observed computer activity; it does not prove intent or comprehension.')
$lines.Add('')
$lines.Add("## Collection window")
$lines.Add("")
$lines.Add("- Samples: $($events.Count)")
$lines.Add("- Approximate observed window: $first–$last")
$lines.Add("- Active samples: $($activeEvents.Count)")
$lines.Add('')
$lines.Add('## Applications')
$lines.Add('')
if ($appRows.Count) {
    $lines.Add('| Application | Samples | Approx. minutes |')
    $lines.Add('|---|---:|---:|')
    foreach ($row in $appRows) { $lines.Add("| $($row.App) | $($row.Samples) | $($row.Minutes) |") }
} else { $lines.Add('_No foreground application samples were collected._') }
$lines.Add('')
$lines.Add('## Project evidence')
$lines.Add('')
if ($projectEvents.Count) {
    foreach ($event in $projectEvents) {
        $lines.Add("- **$($event.projectPath)** — branch `$($event.branch)`, changed files: $($event.changedFileCount), latest commit: `$($event.latestCommit)` $($event.latestCommitMessage)")
    }
} else { $lines.Add('_No configured Git project evidence was collected._') }
$lines.Add('')
$lines.Add('## Limitations')
$lines.Add('')
$lines.Add('- No screenshots, audio, webcam, keystrokes, clipboard, browser contents, document contents, or diffs are included.')
$lines.Add('- Application time is estimated from sampling frequency and excludes detected idle samples.')
Set-Content -LiteralPath $outputPath -Value $lines -Encoding utf8
& (Join-Path $PSScriptRoot 'New-LLMContext.ps1') | Out-Null
Write-Output $outputPath


