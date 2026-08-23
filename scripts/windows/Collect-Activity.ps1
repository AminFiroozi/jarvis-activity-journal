[CmdletBinding()]
param(
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal')
)

$ErrorActionPreference = 'Stop'
$configPath = Join-Path $JournalRoot 'config\settings.json'
$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
. (Join-Path $PSScriptRoot 'Test-ActivityJournalPrivateMode.ps1')
if (Test-ActivityJournalPrivateMode -JournalRoot $JournalRoot) { exit 0 }
$rawRoot = Join-Path $JournalRoot 'raw'
New-Item -ItemType Directory -Force -Path $rawRoot | Out-Null

if (-not ('Jarvis.Activity.Native' -as [type])) {
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ActivityNative {
    [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO info);
}
'@
}

$handle = [ActivityNative]::GetForegroundWindow()
$titleBuilder = New-Object System.Text.StringBuilder ([int]$config.titleMaxLength + 1)
[void][ActivityNative]::GetWindowText($handle, $titleBuilder, $titleBuilder.Capacity)
$title = $titleBuilder.ToString()
$processId = 0
[void][ActivityNative]::GetWindowThreadProcessId($handle, [ref]$processId)
$process = $null
try { $process = Get-Process -Id $processId -ErrorAction Stop } catch {}

foreach ($pattern in @($config.redactTitlePatterns)) {
    if ($title -match $pattern) { $title = '[redacted window title]'; break }
}
if ($title.Length -gt [int]$config.titleMaxLength) { $title = $title.Substring(0, [int]$config.titleMaxLength) + '…' }

$lastInput = New-Object ActivityNative+LASTINPUTINFO
$lastInput.cbSize = [Runtime.InteropServices.Marshal]::SizeOf($lastInput)
$idleSeconds = $null
if ([ActivityNative]::GetLastInputInfo([ref]$lastInput)) {
    $idleMilliseconds = [uint32]([Environment]::TickCount - $lastInput.dwTime)
    $idleSeconds = [math]::Round($idleMilliseconds / 1000, 1)
}

$now = Get-Date
$event = [ordered]@{
    timestamp = $now.ToUniversalTime().ToString('o')
    localTimestamp = $now.ToString('o')
    source = 'foreground-window'
    computer = $env:COMPUTERNAME
    user = $env:USERNAME
    process = if ($process) { $process.ProcessName } else { $null }
    executable = if ($process) { try { $process.Path } catch { $null } } else { $null }
    processId = $processId
    windowTitle = $title
    idleSeconds = $idleSeconds
    active = ($null -eq $idleSeconds -or $idleSeconds -lt ([int]$config.sampleIntervalSeconds * 2))
}
$outputPath = Join-Path $rawRoot ("activity-{0}.jsonl" -f $now.ToString('yyyy-MM-dd'))
($event | ConvertTo-Json -Compress -Depth 5) | Add-Content -LiteralPath $outputPath -Encoding utf8
& (Join-Path $PSScriptRoot 'Write-ActivityJournalHeartbeat.ps1') -JournalRoot $JournalRoot -Service 'collector' -Status 'success' -ItemsProcessed 1 | Out-Null
