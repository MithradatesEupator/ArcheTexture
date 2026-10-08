from __future__ import annotations

import faulthandler
import os
import runpy
import sys
import threading
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

    def fileno(self) -> int:
        return self._stream.fileno()


def show_error(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "ArcheTexture startup failed", 0x10)
    except Exception:
        print(message, file=sys.__stderr__)


def main() -> int:
    if len(sys.argv) not in {3, 4}:
        raise SystemExit("usage: launch_gui.py REPOSITORY LOG_PATH [AUTOMATION_SCRIPT]")
    repo_root = Path(sys.argv[1]).resolve()
    log_path = Path(sys.argv[2]).resolve()
    automation_path = Path(sys.argv[3]).resolve() if len(sys.argv) == 4 else None
    logger = BoundedLog(log_path)
    sys.stdout = logger  # type: ignore[assignment]
    sys.stderr = logger  # type: ignore[assignment]

    def report_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        print("UNHANDLED PYTHON EXCEPTION:")
        print(details)
        show_error(
            f"ArcheTexture encountered an unexpected error and must stop.\n\n"
            f"{exc_type.__name__}: {exc_value}\n\nLog: {log_path}"
        )

    def report_thread_exception(args) -> None:
        print(f"UNHANDLED EXCEPTION IN THREAD {args.thread.name}:")
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=logger)

    sys.excepthook = report_unhandled_exception
    threading.excepthook = report_thread_exception
    faulthandler.enable(file=logger._stream, all_threads=True)
    os.chdir(repo_root)
    sys.path.insert(0, str(repo_root / "src"))
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} Python: {sys.executable}")
    print(f"Repository: {repo_root}")
    print(f"Working directory: {Path.cwd()}")
    print(f"Source path: {repo_root / 'src'}")

    try:
        if automation_path is not None:
            tools_root = (repo_root / "tools").resolve()
            if not automation_path.is_relative_to(tools_root):
                raise ValueError("Automation scripts must be inside this checkout's tools folder")
            namespace = runpy.run_path(str(automation_path))
            run_automation = namespace.get("main")
            if not callable(run_automation):
                raise ValueError(f"Automation script has no callable main(): {automation_path}")
            print(f"Running native GUI automation: {automation_path}")
            result = int(run_automation())
            print(f"Native GUI automation ended with exit code {result}.")
            return result

        from archetexture.ui.main_window import main as run_application

        print("Application import succeeded; entering the normal desktop Qt event loop.")
        result = int(run_application())
        print(f"Application event loop ended with exit code {result}.")
        if result != 0:
            print("STARTUP FAILURE: application returned a nonzero exit code.")
        return result
    except BaseException:
        details = traceback.format_exc()
        if automation_path is not None:
            print("NATIVE GUI AUTOMATION FAILURE:")
            print(details)
            return 1
        message = f"ArcheTexture could not start.\n\n{details}\n\nLog: {log_path}"
        print("STARTUP FAILURE:")
        print(details)
        show_error(message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
