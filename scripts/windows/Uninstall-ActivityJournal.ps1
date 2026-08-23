[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$names = @(
    'Jarvis Activity Journal - Collector',
    'Jarvis Activity Journal - Project Evidence',
    'Jarvis Activity Journal - Content Collector',
    'Jarvis Activity Journal - Screen Capture',
    'Jarvis Activity Journal - Startup',
    'Jarvis Activity Journal - Daily Summary'
)
foreach ($name in $names) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
}
Write-Output 'Activity journal scheduled tasks removed. Existing journal files were preserved.'


