function Test-ActivityJournalPrivateMode {
    param([Parameter(Mandatory)][string]$JournalRoot)

    $statePath = Join-Path $JournalRoot 'config\private-mode.json'
    if (-not (Test-Path -LiteralPath $statePath)) { return $false }
    try {
        $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        return [bool]$state.enabled
    } catch {
        # A malformed state file fails closed to protect private activity.
        return $true
    }
}
