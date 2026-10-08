param(
    [switch]$VerifyOnly,
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$sourceRoot = Join-Path $repoRoot "src"
$launcher = Join-Path $repoRoot "launch_archetexture.vbs"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "ArcheTexture Dev.lnk"
$expectedTarget = Join-Path $env:SystemRoot "System32\wscript.exe"
$stateDir = Join-Path $env:LOCALAPPDATA "ArcheTexture"
$interpreterFile = Join-Path $stateDir "pythonw-path.txt"

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Repo-local launcher not found: $launcher"
}

if (-not $VerifyOnly) {
    $pythonCandidates = [System.Collections.Generic.List[string]]::new()
    if ($PythonPath) {
        $pythonCandidates.Add($PythonPath)
    }
    $repoVenv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $repoVenv) {
        $pythonCandidates.Add($repoVenv)
    }
    if ($env:VIRTUAL_ENV) {
        $pythonCandidates.Add((Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"))
    }
    if ($env:CONDA_PREFIX) {
        $pythonCandidates.Add((Join-Path $env:CONDA_PREFIX "python.exe"))
    }
    $knownPrefixes = @(
        (Join-Path $env:USERPROFILE "miniconda3"),
        (Join-Path $env:USERPROFILE "miniforge3"),
        (Join-Path $env:USERPROFILE "mambaforge"),
        (Join-Path $env:USERPROFILE "anaconda3"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python314"),
        (Join-Path $env:ProgramFiles "Python312"),
        (Join-Path $env:ProgramFiles "Python313"),
        (Join-Path $env:ProgramFiles "Python314")
    )
    foreach ($prefix in $knownPrefixes) {
        $pythonCandidates.Add((Join-Path $prefix "python.exe"))
    }
    $pythonInstalls = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path -LiteralPath $pythonInstalls) {
        Get-ChildItem -LiteralPath $pythonInstalls -Directory | ForEach-Object {
            $pythonCandidates.Add((Join-Path $_.FullName "python.exe"))
        }
    }
    $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        & $pythonLauncher.Source -0p 2>$null | ForEach-Object {
            if ($_ -match "([A-Za-z]:\\.*?python\.exe)\s*$") {
                $pythonCandidates.Add($Matches[1])
            }
        }
    }
    Get-Command python.exe -All -ErrorAction SilentlyContinue | ForEach-Object {
        $pythonCandidates.Add($_.Source)
    }

    $probe = @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r"__SOURCE_ROOT__")))
import numpy
import PIL
import PySide6
import archetexture
from archetexture.ui.main_window import MainWindow
from PySide6.QtWidgets import QApplication
assert Path(archetexture.__file__).resolve().is_relative_to(Path(r"__SOURCE_ROOT__"))
assert len(__import__("archetexture.core.material_starters", fromlist=["MATERIAL_STARTERS"]).MATERIAL_STARTERS) == 18
app = QApplication(["ArcheTexture interpreter verification"])
assert app.platformName().casefold() == "windows", app.platformName()
print(sys.executable)
print(numpy.__version__, PIL.__version__, PySide6.__version__, archetexture.__file__)
'@
    $probe = $probe.Replace("__SOURCE_ROOT__", $sourceRoot)
    $selectedPython = $null
    $selectedPythonw = $null
    $failures = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $explorerPath = @(
        [Environment]::GetEnvironmentVariable("PATH", "Machine"),
        [Environment]::GetEnvironmentVariable("PATH", "User")
    ) -join ";"
    $originalPath = $env:PATH
    $originalPythonPath = $env:PYTHONPATH
    $originalPythonHome = $env:PYTHONHOME
    $originalCondaPrefix = $env:CONDA_PREFIX
    $originalVirtualEnv = $env:VIRTUAL_ENV
    $originalQtPlatform = $env:QT_QPA_PLATFORM

    try {
        Remove-Item Env:PYTHONPATH,Env:PYTHONHOME,Env:CONDA_PREFIX,Env:VIRTUAL_ENV,Env:QT_QPA_PLATFORM `
            -ErrorAction SilentlyContinue
        foreach ($candidate in $pythonCandidates) {
            if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) {
                continue
            }
            $resolvedCandidate = (Resolve-Path -LiteralPath $candidate).Path
            if ($resolvedCandidate -like "*\Microsoft\WindowsApps\*") {
                continue
            }
            if (-not $seen.Add($resolvedCandidate)) {
                continue
            }
            $pythonDir = Split-Path -Parent $resolvedCandidate
            $pythonw = Join-Path $pythonDir "pythonw.exe"
            if (-not (Test-Path -LiteralPath $pythonw)) {
                $failures.Add("No matching pythonw.exe beside $resolvedCandidate")
                continue
            }
            $prefix = $pythonDir
            if ((Split-Path -Leaf $pythonDir) -ieq "Scripts") {
                $prefix = Split-Path -Parent $pythonDir
            }
            $probePath = [System.Collections.Generic.List[string]]::new()
            foreach ($entry in @(
                $pythonDir,
                $prefix,
                (Join-Path $prefix "Library\bin"),
                (Join-Path $prefix "Library\usr\bin"),
                (Join-Path $prefix "Library\mingw-w64\bin"),
                (Join-Path $prefix "Scripts"),
                (Join-Path $prefix "bin")
            )) {
                if ((Test-Path -LiteralPath $entry) -and -not $probePath.Contains($entry)) {
                    $probePath.Add($entry)
                }
            }
            foreach ($entry in ($explorerPath -split ";")) {
                if ($entry) {
                    $probePath.Add($entry)
                }
            }
            $env:PATH = $probePath -join ";"
            $probeOutput = & $resolvedCandidate -c $probe 2>&1
            if ($LASTEXITCODE -eq 0) {
                $selectedPython = $resolvedCandidate
                $selectedPythonw = $pythonw
                break
            }
            $failures.Add("$resolvedCandidate failed runtime/import verification: $($probeOutput -join ' ')")
        }
    } finally {
        $env:PATH = $originalPath
        foreach ($entry in @(
            @{Name="PYTHONPATH";Value=$originalPythonPath},
            @{Name="PYTHONHOME";Value=$originalPythonHome},
            @{Name="CONDA_PREFIX";Value=$originalCondaPrefix},
            @{Name="VIRTUAL_ENV";Value=$originalVirtualEnv},
            @{Name="QT_QPA_PLATFORM";Value=$originalQtPlatform}
        )) {
            if ($null -eq $entry.Value) { Remove-Item "Env:$($entry.Name)" -ErrorAction SilentlyContinue }
            else { Set-Item "Env:$($entry.Name)" $entry.Value }
        }
    }

    if (-not $selectedPythonw) {
        throw "No working Python desktop environment was found. Candidates checked:`n$($failures -join "`n")"
    }

    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    [IO.File]::WriteAllText(
        $interpreterFile,
        $selectedPythonw + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )

    # Replace the existing link so stale arguments or target settings cannot survive.
    if (Test-Path -LiteralPath $shortcutPath) {
        Remove-Item -LiteralPath $shortcutPath -Force
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $expectedTarget
    $shortcut.Arguments = "`"$launcher`""
    $shortcut.WorkingDirectory = $repoRoot
    $shortcut.Description = "Launch the current ArcheTexture development checkout"
    $shortcut.WindowStyle = 1
    $shortcut.Save()
}

if (-not (Test-Path -LiteralPath $interpreterFile)) {
    throw "Verified interpreter path is missing: $interpreterFile"
}
$savedPythonw = (Get-Content -LiteralPath $interpreterFile -Raw).Trim()
if (-not (Test-Path -LiteralPath $savedPythonw)) {
    throw "Saved interpreter no longer exists: $savedPythonw"
}
if (-not (Test-Path -LiteralPath $shortcutPath)) {
    throw "Desktop shortcut is missing: $shortcutPath"
}

$shell = New-Object -ComObject WScript.Shell
$check = $shell.CreateShortcut($shortcutPath)
if ([IO.Path]::GetFullPath($check.TargetPath) -ne [IO.Path]::GetFullPath($expectedTarget) -or
    $check.Arguments -notlike "*$launcher*" -or
    [IO.Path]::GetFullPath($check.WorkingDirectory) -ne $repoRoot) {
    throw "Desktop shortcut target, arguments, or working directory do not match the repo-local launcher."
}
Write-Output "Shortcut: $shortcutPath"
Write-Output "Target: $($check.TargetPath) $($check.Arguments)"
Write-Output "Working directory: $($check.WorkingDirectory)"
Write-Output "Verified pythonw.exe: $savedPythonw"
Write-Output "Interpreter config: $interpreterFile"
