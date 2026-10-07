"""Launch the frozen Windows GUI outside the source tree and Python environment."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path


def main() -> int:
    bundle_dir = Path(
        os.environ.get("ARCHETEXTURE_BUNDLE_DIR", "dist/ArcheTexture-0.1.0-windows-x86_64")
    )
    executable = (bundle_dir / "ArcheTexture-0.1.0-windows-x86_64.exe").resolve()
    assert executable.is_file(), f"Packaged executable missing: {executable}"
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(
        prefix="archetexture-frozen-smoke-", ignore_cleanup_errors=True
    ) as temporary:
        process = subprocess.Popen([str(executable)], cwd=temporary, env=environment)
        try:
            time.sleep(8)
            assert process.poll() is None, f"Frozen application exited early: {process.returncode}"
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    print("Frozen Windows GUI remained running for 8 seconds from an unrelated working directory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
