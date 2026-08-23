[CmdletBinding()]
param(
    [datetime]$Date = (Get-Date),
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal')
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath (Join-Path $JournalRoot 'config\settings.json') | ConvertFrom-Json
$analyzer = $config.screenshotAnalyzer
if (-not $analyzer.enabled) { Write-Output 'Screenshot analyzer disabled.'; exit 0 }
$scriptPath = Join-Path $analyzer.repositoryPath 'src\analyze_screenshots.py'
if (-not (Test-Path -LiteralPath $scriptPath)) { throw "Analyzer script not found: $scriptPath" }

python $scriptPath --journal-root $JournalRoot --date $Date.ToString('yyyy-MM-dd') --endpoint $analyzer.endpoint --model $analyzer.model --api-key-env $analyzer.apiKeyEnv --max-screenshots $analyzer.maxScreenshotsPerRun


