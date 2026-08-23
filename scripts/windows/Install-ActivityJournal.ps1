[CmdletBinding()]
param(
    [switch]$CurrentUserOnly
)

$ErrorActionPreference = 'Stop'
$scriptRoot = $PSScriptRoot
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$collector = Join-Path $scriptRoot 'Collect-Activity.ps1'
$evidence = Join-Path $scriptRoot 'Collect-ProjectEvidence.ps1'
$content = Join-Path $scriptRoot 'Collect-ActiveContent.ps1'
$screen = Join-Path $scriptRoot 'Capture-Screen.ps1'
$summary = Join-Path $scriptRoot 'New-ActivitySummary.ps1'
$startup = Join-Path $scriptRoot 'Run-ActivityJournalNow.ps1'
$launcher = Join-Path $scriptRoot 'Run-Hidden.vbs'
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
$actionArgs = { param($path) "`"$launcher`" `"$path`"" }

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew -StartWhenAvailable

function Register-JarvisTask {
    param([string]$Name, [string]$ScriptPath, [object[]]$Trigger)
    $action = New-ScheduledTaskAction -Execute $wscript -Argument (& $actionArgs $ScriptPath)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Trigger -Principal $principal -Settings $settings -Force | Out-Null
}

$firstRun = (Get-Date).AddMinutes(1)
$collectorTrigger = New-ScheduledTaskTrigger -Once -At $firstRun -RepetitionInterval (New-TimeSpan -Minutes 1)
$evidenceTrigger = New-ScheduledTaskTrigger -Once -At $firstRun -RepetitionInterval (New-TimeSpan -Minutes 15)
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$summaryTrigger = New-ScheduledTaskTrigger -Daily -At '23:55'

Register-JarvisTask -Name 'Jarvis Activity Journal - Collector' -ScriptPath $collector -Trigger $collectorTrigger
Register-JarvisTask -Name 'Jarvis Activity Journal - Project Evidence' -ScriptPath $evidence -Trigger $evidenceTrigger
Register-JarvisTask -Name 'Jarvis Activity Journal - Content Collector' -ScriptPath $content -Trigger $collectorTrigger
Register-JarvisTask -Name 'Jarvis Activity Journal - Screen Capture' -ScriptPath $screen -Trigger $collectorTrigger
Register-JarvisTask -Name 'Jarvis Activity Journal - Startup' -ScriptPath $startup -Trigger $logonTrigger
Register-JarvisTask -Name 'Jarvis Activity Journal - Daily Summary' -ScriptPath $summary -Trigger $summaryTrigger

Write-Output 'Installed scheduled tasks:'
Get-ScheduledTask -TaskName 'Jarvis Activity Journal -*' | Select-Object TaskName, State


