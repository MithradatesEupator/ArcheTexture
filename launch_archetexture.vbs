Option Explicit

Dim shell, files, repoRoot, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
repoRoot = files.GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & _
          Chr(34) & files.BuildPath(repoRoot, "launch_archetexture.ps1") & Chr(34)
shell.Run command, 0, False
