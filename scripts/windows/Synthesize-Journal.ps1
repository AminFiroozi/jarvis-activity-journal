[CmdletBinding()]
param(
    [datetime]$Date = (Get-Date),
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal')
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath (Join-Path $JournalRoot 'config\settings.json') | ConvertFrom-Json
$synthesis = $config.journalSynthesis
if (-not $synthesis.enabled) { Write-Output 'Journal synthesis disabled.'; exit 0 }
$scriptPath = Join-Path $synthesis.repositoryPath 'src\synthesize_journal.py'
if (-not (Test-Path -LiteralPath $scriptPath)) { throw "Synthesis script not found: $scriptPath" }
python $scriptPath --journal-root $JournalRoot --date $Date.ToString('yyyy-MM-dd') --endpoint $synthesis.endpoint --model $synthesis.model --api-key-env $synthesis.apiKeyEnv


