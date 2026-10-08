param([switch]$Smoke)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
$sourceRoot = Join-Path $repoRoot "src"
$pythonCandidates = [System.Collections.Generic.List[string]]::new()

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $pythonCandidates.Add($venvPython)
}

if ($env:VIRTUAL_ENV) {
    $pythonCandidates.Add((Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"))
}
if ($env:CONDA_PREFIX) {
    $pythonCandidates.Add((Join-Path $env:CONDA_PREFIX "python.exe"))
}
Get-Command python.exe -All -ErrorAction SilentlyContinue | ForEach-Object {
    $pythonCandidates.Add($_.Source)
}

$env:PYTHONPATH = if ($env:PYTHONPATH) {
    "$sourceRoot$([System.IO.Path]::PathSeparator)$env:PYTHONPATH"
} else {
    $sourceRoot
}
# Never inherit an offscreen Qt setting from a test shell into a desktop launch.
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue

$probe = @'
import numpy
import PIL
import PySide6
from archetexture.core.material_starters import MATERIAL_STARTERS
from archetexture.ui.main_window import MainWindow
assert len(MATERIAL_STARTERS) == 18
'@
$selectedPython = $null
$selectedPythonw = $null
$failures = [System.Collections.Generic.List[string]]::new()
$seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)

foreach ($candidate in $pythonCandidates) {
    if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) {
        continue
    }
    $resolvedCandidate = (Resolve-Path -LiteralPath $candidate).Path
    if (-not $seen.Add($resolvedCandidate)) {
        continue
    }
    $candidatePythonw = Join-Path (Split-Path -Parent $resolvedCandidate) "pythonw.exe"
    if (-not (Test-Path -LiteralPath $candidatePythonw)) {
        $failures.Add("$resolvedCandidate has no matching pythonw.exe.")
        continue
    }

    $probeOutput = & $resolvedCandidate -c $probe 2>&1
    if ($LASTEXITCODE -eq 0) {
        $selectedPython = $resolvedCandidate
        $selectedPythonw = $candidatePythonw
        break
    }
    $failures.Add("$resolvedCandidate cannot load ArcheTexture: $($probeOutput -join ' ')")
}

if (-not $selectedPython) {
    $details = if ($failures.Count) { $failures -join "`n`n" } else { "No Python environment was found." }
    $message = "ArcheTexture could not find a working Python environment.`n`n" +
        "Create the documented .venv with CONTRIBUTING.md, or install the app dependencies " +
        "in a Python environment on PATH.`n`n$details"
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            $message,
            "ArcheTexture launcher error",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    } catch {
        Write-Error $message
    }
    exit 1
}

if ($Smoke) {
    & $selectedPython (Join-Path $repoRoot "tools\launcher_acceptance.py")
    exit $LASTEXITCODE
}

try {
    Start-Process -FilePath $selectedPythonw `
        -ArgumentList @("-m", "archetexture") `
        -WorkingDirectory $repoRoot `
        -WindowStyle Normal | Out-Null
} catch {
    $message = "ArcheTexture could not be started with:`n$selectedPythonw`n`n$_"
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        $message,
        "ArcheTexture launcher error",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
}
