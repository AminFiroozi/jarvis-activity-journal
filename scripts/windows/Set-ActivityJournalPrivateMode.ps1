[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$JournalRoot,
    [Parameter(Mandatory)]
    [bool]$Enabled,
    [string]$Reason = 'manual'
)

$ErrorActionPreference = 'Stop'
$configDirectory = Join-Path $JournalRoot 'config'
New-Item -ItemType Directory -Force -Path $configDirectory | Out-Null
$state = [ordered]@{
    enabled = $Enabled
    changedAt = (Get-Date).ToUniversalTime().ToString('o')
    reason = $Reason
}
$statePath = Join-Path $configDirectory 'private-mode.json'
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Output $statePath
