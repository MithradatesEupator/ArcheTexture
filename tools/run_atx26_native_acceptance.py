from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))


def main() -> int:
    if os.name != "nt":
        raise SystemExit("ATX 26 acceptance requires native Windows Qt.")

    from archetexture.core.material_starters import MATERIAL_STARTERS

    launcher = REPOSITORY / "launch_archetexture.ps1"
    scenario = REPOSITORY / "tools" / "atx26_native_scenario.py"
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    report_root = Path(tempfile.mkdtemp(prefix=".tmp-atx26-run-", dir=REPOSITORY))
    evidence_dir = REPOSITORY / ".tmp-atx26-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    cases = ["default", *(starter.name for starter in MATERIAL_STARTERS)]
    results = []
    failures = []

    for index, starter_name in enumerate(cases):
        report_path = report_root / f"{index:02d}.json"
        environment = os.environ.copy()
        for key in (
            "CONDA_PREFIX",
            "VIRTUAL_ENV",
            "PYTHONPATH",
            "PYTHONHOME",
            "QT_QPA_PLATFORM",
        ):
            environment.pop(key, None)
        environment["ATX26_STARTER"] = starter_name
        environment["ATX26_REPORT"] = str(report_path)
        environment["ATX26_EVIDENCE_DIR"] = str(evidence_dir)
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
            timeout=180,
            check=False,
        )
        if not report_path.is_file():
            active_log = Path(os.environ.get("LOCALAPPDATA", "")) / "ArcheTexture" / "launcher.log"
            log_copy = report_root / f"{index:02d}-launcher.log"
            if active_log.is_file():
                shutil.copyfile(active_log, log_copy)
            failures.append(
                f"{starter_name}: native process exited {completed.returncode} without a report; "
                f"launcher log: {log_copy}; stdout={completed.stdout!r}; "
                f"stderr={completed.stderr!r}"
            )
            continue
        result = json.loads(report_path.read_text(encoding="utf-8"))
        if "result" not in result:
            active_log = Path(os.environ.get("LOCALAPPDATA", "")) / "ArcheTexture" / "launcher.log"
            log_copy = report_root / f"{index:02d}-launcher.log"
            if active_log.is_file():
                shutil.copyfile(active_log, log_copy)
            failures.append(
                f"{starter_name}: native process exited {completed.returncode} before completing; "
                f"launcher log: {log_copy}"
            )
            continue
        result["process_exit_code"] = completed.returncode
        results.append(result)
        print(
            f"{starter_name}: {result['result']} · {result['qt_platform']} Qt · "
            f"material stddev {result['material']['stddev']:.1f} · exit {completed.returncode}",
            flush=True,
        )
        if completed.returncode != 0 or result.get("result") != "passed":
            failures.append(
                f"{starter_name}: native scenario failed with exit {completed.returncode}"
            )

    representative_names = (
        "Rough Stone",
        "Weathered Metal",
        "Wood Grain",
        "Fabric",
        "Brick",
    )
    representative_images = {
        name: np.asarray(
            Image.open(evidence_dir / f"atx26-{name.replace('/', '-')}-material.png").convert(
                "RGB"
            ),
            dtype=np.float32,
        )
        for name in representative_names
    }
    representative_differences = {}
    for index, first in enumerate(representative_names):
        for second in representative_names[index + 1 :]:
            a, b = representative_images[first], representative_images[second]
            height, width = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
            ay, ax = (a.shape[0] - height) // 2, (a.shape[1] - width) // 2
            by, bx = (b.shape[0] - height) // 2, (b.shape[1] - width) // 2
            a_center = a[ay : ay + height, ax : ax + width]
            b_center = b[by : by + height, bx : bx + width]
            difference = float(np.mean(np.abs(a_center - b_center)))
            representative_differences[f"{first} / {second}"] = difference
            if difference <= 3.0:
                failures.append(
                    f"representative starters are visually too similar: {first} / {second} "
                    f"(mean framebuffer difference {difference:.2f})"
                )

    summary_path = evidence_dir / "atx26-native-summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "cases": results,
                "representative_frame_differences": representative_differences,
                "failures": failures,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if failures:
        raise RuntimeError(f"Native acceptance failures: {failures}; report: {summary_path}")
    print(f"All {len(results)} native Windows cases passed; report: {summary_path}")
    shutil.rmtree(report_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
