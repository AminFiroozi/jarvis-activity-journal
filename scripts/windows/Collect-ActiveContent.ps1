[CmdletBinding()]
param(
    [string]$JournalRoot = (Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) 'Journal')
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath (Join-Path $JournalRoot 'config\settings.json') | ConvertFrom-Json
. (Join-Path $PSScriptRoot 'Test-ActivityJournalPrivateMode.ps1')
if (Test-ActivityJournalPrivateMode -JournalRoot $JournalRoot) { exit 0 }
if (-not $config.contentCapture.enabled) { exit 0 }
if ($null -ne $config.privacy -and $config.privacy.captureEnabled -eq $false) { exit 0 }

if (-not ('ActivityNative' -as [type])) {
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ActivityNative {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
'@
}
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

$handle = [ActivityNative]::GetForegroundWindow()
$processId = 0
[void][ActivityNative]::GetWindowThreadProcessId($handle, [ref]$processId)
try { $process = Get-Process -Id $processId -ErrorAction Stop } catch { exit 0 }
if ($config.contentCapture.allowedProcessNames -notcontains $process.ProcessName) { exit 0 }

$root = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
if ($null -eq $root) { exit 0 }
$windowTitle = $root.Current.Name
if ($null -ne $config.privacy) {
    if (@($config.privacy.excludedApplications) -contains $process.ProcessName) { exit 0 }
    foreach ($titlePattern in @($config.privacy.excludedWindowTitlePatterns)) {
        if (-not [string]::IsNullOrWhiteSpace($titlePattern) -and $windowTitle -match $titlePattern) { exit 0 }
    }
}
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$parts = [System.Collections.Generic.List[string]]::new()
$script:elementCount = 0

function Visit-Element {
    param([System.Windows.Automation.AutomationElement]$Element)
    if ($script:elementCount -ge [int]$config.contentCapture.maxElementCount) { return }
    try {
        $controlType = $Element.Current.ControlType.ProgrammaticName
        if ($controlType -match 'Text|Edit|ListItem|Document|TabItem') {
            $value = $null
            $pattern = $null
            if ($Element.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$pattern)) {
                $value = $pattern.DocumentRange.GetText(2000)
            }
            if ([string]::IsNullOrWhiteSpace($value)) { $value = $Element.Current.Name }
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                $clean = $value.Trim()
                if ($null -eq $config.privacy -or $config.privacy.redactBeforeStorage -ne $false) {
                    foreach ($redactPattern in @($config.contentCapture.redactTextPatterns)) {
                        $clean = [regex]::Replace($clean, $redactPattern, '[REDACTED]')
                    }
                }
                if ($clean.Length -gt 2000) { $clean = $clean.Substring(0, 2000) + '…' }
                if (-not $parts.Contains($clean)) { $parts.Add($clean); $script:elementCount++ }
            }
        }
        $child = $walker.GetFirstChild($Element)
        while ($null -ne $child -and $script:elementCount -lt [int]$config.contentCapture.maxElementCount) {
            Visit-Element -Element $child
            $child = $walker.GetNextSibling($child)
        }
    } catch { }
}

Visit-Element -Element $root
$text = ($parts -join "`n")
if ([string]::IsNullOrWhiteSpace($text)) { exit 0 }
if ($text.Length -gt [int]$config.contentCapture.maxTextLength) { $text = $text.Substring(0, [int]$config.contentCapture.maxTextLength) + '…' }

$now = Get-Date
$rawRoot = Join-Path $JournalRoot 'raw'
New-Item -ItemType Directory -Force -Path $rawRoot | Out-Null
$outputPath = Join-Path $rawRoot ("content-{0}.jsonl" -f $now.ToString('yyyy-MM-dd'))
$event = [ordered]@{
    timestamp = $now.ToUniversalTime().ToString('o')
    localTimestamp = $now.ToString('o')
    source = 'focused-content'
    process = $process.ProcessName
    processId = $processId
    content = $text
    captureMode = 'Windows UI Automation; focused window only'
}
($event | ConvertTo-Json -Compress -Depth 5) | Add-Content -LiteralPath $outputPath -Encoding utf8
