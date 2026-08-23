[CmdletBinding()]
param(
    [switch]$Summary
)

$ErrorActionPreference = 'Stop'
$scriptRoot = $PSScriptRoot
& (Join-Path $scriptRoot 'Collect-Activity.ps1')
& (Join-Path $scriptRoot 'Collect-ProjectEvidence.ps1')
& (Join-Path $scriptRoot 'Collect-ActiveContent.ps1')
& (Join-Path $scriptRoot 'Capture-Screen.ps1')
if ($Summary) { & (Join-Path $scriptRoot 'New-ActivitySummary.ps1') }
& (Join-Path $scriptRoot 'New-LLMContext.ps1')
Write-Output 'Activity journal collection completed.'


