[CmdletBinding()]
param(
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal'),
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$arguments = @((Join-Path $repoRoot 'src\doctor.py'), '--journal-root', $JournalRoot)
if ($Json) { $arguments += '--json' }
python @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
    $expected = @(
        'Jarvis Activity Journal - Collector',
        'Jarvis Activity Journal - Content Collector',
        'Jarvis Activity Journal - Daily Summary',
        'Jarvis Activity Journal - Project Evidence',
        'Jarvis Activity Journal - Screen Capture'
    )
    foreach ($name in $expected) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task) { Write-Output "[PASS] scheduled-task: $name ($($task.State))" }
        else { Write-Output "[WARN] scheduled-task: $name is not installed" }
    }
}
