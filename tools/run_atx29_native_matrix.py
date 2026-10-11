from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
NATIVE_CASES = (
    "default",
    "Rough Stone",
    "Weathered Metal",
    "Wood Grain",
    "Fabric",
    "Brick",
)


def main() -> int:
    if os.name != "nt":
        raise SystemExit("ATX 29 native GUI matrix requires Windows.")
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    launcher = REPOSITORY / "launch_archetexture.ps1"
    scenario = REPOSITORY / "tools" / "atx29_spinbox_scenario.py"
    report_root = REPOSITORY / ".tmp-atx29-native"
    isolated_local = report_root / "Local"
    isolated_roaming = report_root / "Roaming"
    state = isolated_local / "ArcheTexture"
    state.mkdir(parents=True, exist_ok=True)
    interpreter = Path(os.environ["LOCALAPPDATA"]) / "ArcheTexture" / "pythonw-path.txt"
    shutil.copyfile(interpreter, state / "pythonw-path.txt")

    results = []
    failures = []
    for index, starter in enumerate(NATIVE_CASES):
        slug = starter.lower().replace(" ", "-").replace("/", "-")
        report = report_root / f"{index:02d}-{slug}.json"
        report.unlink(missing_ok=True)
        environment = os.environ.copy()
        for key in (
            "CONDA_PREFIX",
            "VIRTUAL_ENV",
            "PYTHONPATH",
            "PYTHONHOME",
            "QT_QPA_PLATFORM",
        ):
            environment.pop(key, None)
        environment["LOCALAPPDATA"] = str(isolated_local)
        environment["APPDATA"] = str(isolated_roaming)
        environment["ATX29_REPORT"] = str(report)
        environment["ATX29_STARTER"] = starter
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
            cwd=Path(os.environ.get("TEMP", str(REPOSITORY))),
            env=environment,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        log_copy = report_root / f"{index:02d}-{slug}-launcher.log"
        active_log = state / "launcher.log"
        if active_log.is_file():
            shutil.copyfile(active_log, log_copy)
        if not report.is_file():
            failures.append(
                f"{starter}: launcher exit {completed.returncode} without a report; "
                f"log={log_copy}; stdout={completed.stdout!r}; stderr={completed.stderr!r}"
            )
            continue
        result = json.loads(report.read_text(encoding="utf-8"))
        result["launcher_exit_code"] = completed.returncode
        results.append(result)
        print(
            f"{starter}: {result.get('result')} · launcher exit {completed.returncode}",
            flush=True,
        )
        if completed.returncode != 0 or result.get("result") != "passed":
            failures.append(f"{starter}: {result}; launcher log={log_copy}")

    summary = {"results": results, "failures": failures}
    (report_root / "matrix-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Passed {len(results)} native Windows cases.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
