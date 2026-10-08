param([switch]$VerifyOnly)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcher = Join-Path $repoRoot "launch_archetexture.vbs"
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Repo-local launcher not found: $launcher"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "ArcheTexture Dev.lnk"
$expectedTarget = Join-Path $env:SystemRoot "System32\wscript.exe"
$shell = New-Object -ComObject WScript.Shell
if (-not $VerifyOnly) {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $expectedTarget
    $shortcut.Arguments = "`"$launcher`""
    $shortcut.WorkingDirectory = $repoRoot
    $shortcut.Description = "Launch the current ArcheTexture development checkout"
    $shortcut.WindowStyle = 1
    $shortcut.Save()
}

$check = $shell.CreateShortcut($shortcutPath)
if ([IO.Path]::GetFullPath($check.TargetPath) -ne [IO.Path]::GetFullPath($expectedTarget) -or
    $check.Arguments -notlike "*$launcher*") {
    throw "Shortcut was created but does not resolve to the repo-local launcher."
}
Write-Output "Shortcut: $shortcutPath"
Write-Output "Target: $($check.TargetPath) $($check.Arguments)"
