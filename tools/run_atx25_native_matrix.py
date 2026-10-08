from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from archetexture.core.material_starters import MATERIAL_STARTERS  # noqa: E402


def main() -> int:
    if os.name != "nt":
        raise SystemExit("The ATX 25 GUI matrix requires native Windows Qt.")

    launcher = REPOSITORY / "launch_archetexture.ps1"
    scenario = REPOSITORY / "tools" / "atx25_layer_edit_scenario.py"
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    report_root = Path(tempfile.mkdtemp(prefix=".atx25-native-matrix-", dir=REPOSITORY))
    cases = [("default", 3), *((starter.name, 1) for starter in MATERIAL_STARTERS)]
    results = []

    for case_index, (starter_name, repetitions) in enumerate(cases):
        for repeat in range(repetitions):
            case_name = f"{case_index:02d}-{repeat + 1:02d}"
            case_report = report_root / f"{case_name}.json"
            case_log = report_root / f"{case_name}.launcher.log"
            environment = os.environ.copy()
            for key in (
                "CONDA_PREFIX",
                "VIRTUAL_ENV",
                "PYTHONPATH",
                "PYTHONHOME",
                "QT_QPA_PLATFORM",
            ):
                environment.pop(key, None)
            environment["ATX25_STARTER"] = starter_name
            environment["ATX25_REPORT"] = str(case_report)
            command = [
                str(powershell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(launcher),
                "-AutomationScript",
                str(scenario),
                "-WaitForExit",
            ]
            completed = subprocess.run(
                command,
                cwd=Path(tempfile.gettempdir()),
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            active_log = Path(os.environ.get("LOCALAPPDATA", "")) / "ArcheTexture" / "launcher.log"
            if active_log.is_file():
                try:
                    shutil.copyfile(active_log, case_log)
                except OSError as exc:
                    result_log_error = str(exc)
                else:
                    result_log_error = None
            else:
                result_log_error = "launcher log was not readable"
            if not case_report.is_file():
                raise RuntimeError(
                    f"{starter_name}: native process exited {completed.returncode} "
                    f"without a report; see {case_log}. "
                    f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
                )
            result = json.loads(case_report.read_text(encoding="utf-8"))
            result.update(
                {
                    "process_exit_code": completed.returncode,
                    "launcher_log": str(case_log),
                    "stdout": completed.stdout.strip(),
                    "stderr": completed.stderr.strip(),
                    "launcher_log_copy_error": result_log_error,
                }
            )
            results.append(result)
            print(
                f"{starter_name} (run {repeat + 1}/{repetitions}): "
                f"{result['result']} · native {result.get('qt_platform')} Qt · "
                f"exit {completed.returncode}",
                flush=True,
            )
            if completed.returncode != 0 or result.get("result") != "passed":
                summary = report_root / "summary.json"
                summary.write_text(json.dumps(results, indent=2), encoding="utf-8")
                raise RuntimeError(
                    f"Native GUI matrix failed for {starter_name}; "
                    f"details: {summary} and {case_log}"
                )

    summary = report_root / "summary.json"
    summary.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"All {len(results)} native Windows launcher cases passed.")
    shutil.rmtree(report_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
