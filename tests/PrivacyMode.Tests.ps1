Describe 'Activity journal private mode' {
    BeforeEach {
        $testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("jarvis-private-mode-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path (Join-Path $testRoot 'config') -Force | Out-Null
    }

    AfterEach {
        if (Test-Path -LiteralPath $testRoot) {
            Remove-Item -LiteralPath $testRoot -Recurse -Force
        }
    }

    It 'writes and clears a timestamped private-mode state file' {
        & "$PSScriptRoot\..\scripts\windows\Set-ActivityJournalPrivateMode.ps1" -JournalRoot $testRoot -Enabled $true -Reason 'test'
        $statePath = Join-Path $testRoot 'config\private-mode.json'
        $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json

        $state.enabled | Should Be $true
        $state.reason | Should Be 'test'
        $state.changedAt | Should Not BeNullOrEmpty

        & "$PSScriptRoot\..\scripts\windows\Set-ActivityJournalPrivateMode.ps1" -JournalRoot $testRoot -Enabled $false -Reason 'resume'
        $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        $state.enabled | Should Be $false
        $state.reason | Should Be 'resume'
    }

    It 'uses privacy retention and reports removed files' {
        $config = @{ retentionDays = 90; privacy = @{ retentionDays = 1 } } | ConvertTo-Json -Depth 4
        $config | Set-Content -LiteralPath (Join-Path $testRoot 'config\settings.json') -Encoding UTF8
        $raw = Join-Path $testRoot 'raw'
        New-Item -ItemType Directory -Path $raw -Force | Out-Null
        $oldFile = Join-Path $raw 'old.jsonl'
        'old' | Set-Content -LiteralPath $oldFile
        (Get-Item -LiteralPath $oldFile).LastWriteTime = (Get-Date).AddDays(-2)

        $output = & "$PSScriptRoot\..\scripts\windows\Invoke-RetentionCleanup.ps1" -JournalRoot $testRoot | ConvertFrom-Json

        $output.retentionDays | Should Be 1
        $output.removedFiles | Should Be 1
        (Test-Path -LiteralPath $oldFile) | Should Be $false
    }
}
