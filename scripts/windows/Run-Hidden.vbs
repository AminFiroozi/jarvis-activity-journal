Option Explicit

Dim shell, scriptPath, command
If WScript.Arguments.Count < 1 Then WScript.Quit 2

scriptPath = WScript.Arguments(0)
Set shell = CreateObject("WScript.Shell")
command = "pwsh.exe -WindowStyle Hidden -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " & Chr(34) & scriptPath & Chr(34)
shell.Run command, 0, False


