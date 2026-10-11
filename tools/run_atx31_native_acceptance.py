from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


def main() -> int:
    if os.name != "nt":
        raise SystemExit("ATX 31 native acceptance requires Windows.")
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    root = REPOSITORY / ".tmp-atx31-native"
    local_app_data = root / "Local"
    roaming_app_data = root / "Roaming"
    state = local_app_data / "ArcheTexture"
    state.mkdir(parents=True, exist_ok=True)
    roaming_app_data.mkdir(parents=True, exist_ok=True)
    interpreter_config = Path(os.environ["LOCALAPPDATA"]) / "ArcheTexture" / "pythonw-path.txt"
    shutil.copyfile(interpreter_config, state / "pythonw-path.txt")

    report = root / "native-journey.json"
    evidence = root / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    environment = os.environ.copy()
    for name in ("CONDA_PREFIX", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "QT_QPA_PLATFORM"):
        environment.pop(name, None)
    environment["LOCALAPPDATA"] = str(local_app_data)
    environment["APPDATA"] = str(roaming_app_data)
    environment["ATX31_REPORT"] = str(report)
    environment["ATX31_EVIDENCE_DIR"] = str(evidence)
    launcher = REPOSITORY / "launch_archetexture.ps1"
    scenario = REPOSITORY / "tools" / "atx31_native_scenario.py"
    completed = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher),
            "-AutomationScript",
            str(scenario),
            "-WaitForExit",
        ],
        cwd=Path(os.environ.get("TEMP", str(REPOSITORY))),
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if not report.is_file():
        raise RuntimeError(
            "The native application did not produce its report. "
            f"Exit code: {completed.returncode}; stdout: {completed.stdout}; "
            f"stderr: {completed.stderr}; launcher log: {state / 'launcher.log'}"
        )
    result = json.loads(report.read_text(encoding="utf-8"))
    result["process_exit_code"] = completed.returncode
    result["evidence_directory"] = str(evidence)
    result["launcher_log"] = str(state / "launcher.log")
    summary = root / "summary.json"
    summary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if completed.returncode or result.get("result") != "passed":
        raise RuntimeError(f"Native journey failed: {result}; summary: {summary}")
    print(f"Native Windows Qt journey passed (exit {completed.returncode}); {summary}")
    print(f"Framebuffer evidence: {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
