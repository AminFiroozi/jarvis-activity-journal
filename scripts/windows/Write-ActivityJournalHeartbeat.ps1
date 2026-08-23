[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$JournalRoot,
    [Parameter(Mandatory)][string]$Service,
    [ValidateSet('started', 'success', 'failed')][string]$Status = 'started',
    [int]$ItemsProcessed = 0,
    [string]$ErrorMessage
)

$ErrorActionPreference = 'Stop'
$healthDirectory = Join-Path $JournalRoot 'health'
New-Item -ItemType Directory -Force -Path $healthDirectory | Out-Null
$path = Join-Path $healthDirectory ("{0}.json" -f $Service)
$existing = $null
if (Test-Path -LiteralPath $path) {
    try { $existing = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json } catch {}
}
$now = (Get-Date).ToUniversalTime().ToString('o')
$heartbeat = [ordered]@{
    service = $Service
    status = $Status
    startedAt = if ($existing) { $existing.startedAt } else { $now }
    lastSuccessAt = if ($Status -eq 'success') { $now } elseif ($existing) { $existing.lastSuccessAt } else { $null }
    lastErrorAt = if ($Status -eq 'failed') { $now } elseif ($existing) { $existing.lastErrorAt } else { $null }
    lastError = if ($Status -eq 'failed') { $ErrorMessage } elseif ($existing) { $existing.lastError } else { $null }
    itemsProcessed = $ItemsProcessed
    updatedAt = $now
}
$temporaryPath = "$path.tmp"
$heartbeat | ConvertTo-Json | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
Move-Item -LiteralPath $temporaryPath -Destination $path -Force
Write-Output $path
