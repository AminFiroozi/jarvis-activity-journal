Describe 'Activity journal health heartbeat' {
    It 'writes a structured heartbeat with success metadata' {
        $root = Join-Path ([System.IO.Path]::GetTempPath()) ("jarvis-health-" + [guid]::NewGuid().ToString('N'))
        try {
            & "$PSScriptRoot\..\scripts\windows\Write-ActivityJournalHeartbeat.ps1" -JournalRoot $root -Service 'test-worker' -Status 'success' -ItemsProcessed 3
            $heartbeat = Get-Content -Raw -LiteralPath (Join-Path $root 'health\test-worker.json') | ConvertFrom-Json

            $heartbeat.service | Should Be 'test-worker'
            $heartbeat.status | Should Be 'success'
            $heartbeat.itemsProcessed | Should Be 3
            $heartbeat.lastSuccessAt | Should Not BeNullOrEmpty
        }
        finally {
            if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
        }
    }
}
