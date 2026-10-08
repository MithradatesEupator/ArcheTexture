$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$sourceRoot = Join-Path $repoRoot "src"
$localAppData = if ($env:LOCALAPPDATA) {
    $env:LOCALAPPDATA
} else {
    Join-Path $env:USERPROFILE "AppData\Local"
}
$stateDir = Join-Path $localAppData "ArcheTexture"
$interpreterFile = Join-Path $stateDir "pythonw-path.txt"
$logPath = Join-Path $stateDir "launcher.log"

New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
Set-Content -LiteralPath $logPath -Encoding UTF8 -Value @(
    "ArcheTexture launcher: $(Get-Date -Format o)",
    "Repository: $repoRoot",
    "Interpreter config: $interpreterFile"
)

function Add-LauncherLog([string]$message) {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "$(Get-Date -Format o) $message"
}

function Show-LauncherError([string]$message) {
    Add-LauncherLog "STARTUP FAILURE: $message"
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "$message`n`nDetails were saved to:`n$logPath",
            "ArcheTexture launcher error",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    } catch {
        Write-Error "$message`nLauncher log: $logPath"
    }
}

if (-not (Test-Path -LiteralPath $interpreterFile)) {
    Show-LauncherError "No verified Python interpreter is configured. Run tools\create_desktop_shortcut.ps1 from this checkout to repair the shortcut and interpreter setup."
    exit 1
}

$pythonw = (Get-Content -LiteralPath $interpreterFile -Raw).Trim()
if (-not [IO.Path]::IsPathRooted($pythonw) -or
    [IO.Path]::GetFileName($pythonw) -ine "pythonw.exe" -or
    -not (Test-Path -LiteralPath $pythonw)) {
    Show-LauncherError "The saved pythonw.exe path is missing or invalid: $pythonw. Rerun tools\create_desktop_shortcut.ps1 to select a working interpreter."
    exit 1
}

$python = Join-Path (Split-Path -Parent $pythonw) "python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Show-LauncherError "The matching python.exe was not found beside the saved interpreter: $pythonw"
    exit 1
}

# Build a stable runtime PATH from this interpreter and the real Windows
# machine/user PATH values. Do not inherit an activated coding shell.
$pythonDir = Split-Path -Parent $pythonw
$prefix = $pythonDir
if ((Split-Path -Leaf $pythonDir) -ieq "Scripts") {
    $prefix = Split-Path -Parent $pythonDir
}
$runtimePaths = [System.Collections.Generic.List[string]]::new()
foreach ($path in @(
    $pythonDir,
    $prefix,
    (Join-Path $prefix "Library\bin"),
    (Join-Path $prefix "Library\usr\bin"),
    (Join-Path $prefix "Library\mingw-w64\bin"),
    (Join-Path $prefix "Scripts"),
    (Join-Path $prefix "bin")
)) {
    if ((Test-Path -LiteralPath $path) -and -not $runtimePaths.Contains($path)) {
        $runtimePaths.Add($path)
    }
}
$machinePath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
foreach ($entry in @($machinePath, $userPath) -split ";") {
    if ($entry) {
        $runtimePaths.Add($entry)
    }
}
$env:PATH = $runtimePaths -join ";"
$env:PYTHONPATH = $sourceRoot
Remove-Item Env:PYTHONHOME,Env:CONDA_PREFIX,Env:VIRTUAL_ENV,Env:QT_QPA_PLATFORM `
    -ErrorAction SilentlyContinue

$bootstrap = Join-Path $repoRoot "tools\launch_gui.py"
if (-not (Test-Path -LiteralPath $bootstrap)) {
    Show-LauncherError "The current checkout is missing tools\launch_gui.py: $repoRoot"
    exit 1
}

$arguments = '"{0}" "{1}" "{2}"' -f $bootstrap, $repoRoot, $logPath
Add-LauncherLog "Selected pythonw.exe: $pythonw"
Add-LauncherLog "Launch command: `"$pythonw`" $arguments"
Add-LauncherLog "Working directory: $repoRoot"

try {
    $process = Start-Process -FilePath $pythonw `
        -ArgumentList $arguments `
        -WorkingDirectory $repoRoot `
        -WindowStyle Normal `
        -PassThru
    Start-Sleep -Milliseconds 1200
    $process.Refresh()
    if ($process.HasExited -and $process.ExitCode -ne 0) {
        $tail = (Get-Content -LiteralPath $logPath -Tail 20) -join "`n"
        Show-LauncherError "ArcheTexture exited during startup (code $($process.ExitCode)).`n$tail"
        exit 1
    }
} catch {
    Show-LauncherError "ArcheTexture could not be started with $pythonw.`n$_"
    exit 1
}
