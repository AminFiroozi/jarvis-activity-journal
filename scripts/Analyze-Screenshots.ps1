[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$JournalRoot,
    [Parameter(Mandatory)] [string]$Endpoint,
    [Parameter(Mandatory)] [string]$Model,
    [string]$Date = (Get-Date -Format 'yyyy-MM-dd'),
    [string]$ApiKeyEnv = 'VISION_API_KEY',
    [int]$MaxScreenshots = 12
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
python (Join-Path $repoRoot 'src\analyze_screenshots.py') --journal-root $JournalRoot --date $Date --endpoint $Endpoint --model $Model --api-key-env $ApiKeyEnv --max-screenshots $MaxScreenshots
