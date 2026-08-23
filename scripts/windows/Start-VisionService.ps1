[CmdletBinding()]
param(
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal')
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath (Join-Path $JournalRoot 'config\settings.json') | ConvertFrom-Json
if (-not $config.visionService.enabled) { exit 0 }
$logPath = Join-Path (Join-Path $JournalRoot 'raw') 'vision-service.log'
New-Item -ItemType Directory -Force -Path (Split-Path $logPath -Parent) | Out-Null
$lms = (Get-Command lms -ErrorAction Stop).Source

"[$(Get-Date -Format o)] Starting LM Studio server" | Add-Content -LiteralPath $logPath
Start-Process -FilePath $lms -ArgumentList 'server start' -WindowStyle Hidden | Out-Null
Start-Sleep -Seconds 8

if (-not $config.visionService.loadOnLogon) { exit 0 }
$modelsJson = & $lms ls --json 2>> $logPath | Out-String
try { $models = $modelsJson | ConvertFrom-Json } catch { "[$(Get-Date -Format o)] Model list unavailable: $modelsJson" | Add-Content -LiteralPath $logPath; exit 0 }
$modelText = $modelsJson
if ($modelText -notmatch [regex]::Escape($config.visionService.modelPattern)) {
    "[$(Get-Date -Format o)] Vision model not downloaded yet; pattern '$($config.visionService.modelPattern)' not found" | Add-Content -LiteralPath $logPath
    exit 0
}
$modelLine = ($modelText -split "`r?`n" | Where-Object { $_ -match [regex]::Escape($config.visionService.modelPattern) } | Select-Object -First 1)
$modelKey = $null
if ($modelLine -match '"modelKey"\s*:\s*"([^"]+)"') { $modelKey = $Matches[1] }
if (-not $modelKey -and $modelLine -match '"key"\s*:\s*"([^"]+)"') { $modelKey = $Matches[1] }
if (-not $modelKey) { "[$(Get-Date -Format o)] Found vision model but could not determine model key" | Add-Content -LiteralPath $logPath; exit 0 }

"[$(Get-Date -Format o)] Loading vision model $modelKey" | Add-Content -LiteralPath $logPath
& $lms load $modelKey --gpu=$($config.visionService.gpu) *>> $logPath


