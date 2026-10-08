Option Explicit

Dim shell, files, repoRoot, command, powershell
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
repoRoot = files.GetParentFolderName(WScript.ScriptFullName)
 powershell = shell.ExpandEnvironmentStrings("%SystemRoot%") & _
              "\System32\WindowsPowerShell\v1.0\powershell.exe"
command = Chr(34) & powershell & Chr(34) & " -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & _
          Chr(34) & files.BuildPath(repoRoot, "launch_archetexture.ps1") & Chr(34)
shell.Run command, 0, False
