from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path


class BoundedLog:
    def __init__(self, path: Path, limit: int = 256 * 1024) -> None:
        self._stream = path.open("a", encoding="utf-8", buffering=1)
        self._written = path.stat().st_size
        self._marker = "\n[launcher log output capped at 256 KiB]\n"
        self._limit = limit - len(self._marker.encode("utf-8"))
        self._marked = False

    def write(self, message: str) -> int:
        encoded = message.encode("utf-8")
        remaining = max(0, self._limit - self._written)
        chunk = encoded[:remaining].decode("utf-8", errors="ignore")
        self._stream.write(chunk)
        self._written += len(chunk.encode("utf-8"))
        if len(chunk.encode("utf-8")) < len(encoded) and not self._marked:
            self._stream.write(self._marker)
            self._written += len(self._marker.encode("utf-8"))
            self._marked = True
        self._stream.flush()
        return len(message)

    def flush(self) -> None:
        self._stream.flush()


def show_error(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "ArcheTexture startup failed", 0x10)
    except Exception:
        print(message, file=sys.__stderr__)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: launch_gui.py REPOSITORY LOG_PATH")
    repo_root = Path(sys.argv[1]).resolve()
    log_path = Path(sys.argv[2]).resolve()
    logger = BoundedLog(log_path)
    sys.stdout = logger  # type: ignore[assignment]
    sys.stderr = logger  # type: ignore[assignment]
    os.chdir(repo_root)
    sys.path.insert(0, str(repo_root / "src"))
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} Python: {sys.executable}")
    print(f"Repository: {repo_root}")
    print(f"Working directory: {Path.cwd()}")
    print(f"Source path: {repo_root / 'src'}")

    try:
        from archetexture.ui.main_window import main as run_application

        print("Application import succeeded; entering the normal desktop Qt event loop.")
        result = int(run_application())
        print(f"Application event loop ended with exit code {result}.")
        if result != 0:
            print("STARTUP FAILURE: application returned a nonzero exit code.")
        return result
    except BaseException:
        details = traceback.format_exc()
        message = f"ArcheTexture could not start.\n\n{details}\n\nLog: {log_path}"
        print("STARTUP FAILURE:")
        print(details)
        show_error(message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
