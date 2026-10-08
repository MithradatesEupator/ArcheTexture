from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time

if os.environ.get("QT_QPA_PLATFORM", "").casefold() in {"offscreen", "minimal"}:
    raise SystemExit("Desktop acceptance requires the normal Windows Qt platform.")

from PySide6.QtWidgets import QApplication

from archetexture.core.material_starters import MATERIAL_STARTERS
from archetexture.ui.main_window import MainWindow
from archetexture.ui.material_starter_dialog import MaterialStarterDialog


def _visible_archetexture_windows() -> list[tuple[int, int, str]]:
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)
    user32.EnumWindows.argtypes = [callback_type, ctypes.c_ssize_t]
    user32.EnumWindows.restype = ctypes.c_bool
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_bool
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    windows: list[tuple[int, int, str]] = []
    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, len(title))
        if "ArcheTexture" not in title.value:
            return True
        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        windows.append((int(hwnd), process_id.value, title.value))
        return True

    user32.EnumWindows(callback_type(visit), 0)
    return windows


def verify_repo_launcher(repo_root: str) -> None:
    shortcut_tool = os.path.join(repo_root, "tools", "create_desktop_shortcut.ps1")
    verification = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            shortcut_tool,
            "-VerifyOnly",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if verification.returncode:
        raise SystemExit(f"Desktop shortcut verification failed: {verification.stderr}")
    shortcut_line = next(
        (line for line in verification.stdout.splitlines() if line.startswith("Shortcut: ")),
        None,
    )
    if not shortcut_line:
        raise SystemExit("Desktop shortcut path was not returned by the verifier.")
    shortcut_path = shortcut_line.removeprefix("Shortcut: ")
    if not os.path.isfile(shortcut_path):
        raise SystemExit(f"Desktop shortcut does not exist: {shortcut_path}")

    baseline_pids = {pid for _hwnd, pid, _title in _visible_archetexture_windows()}
    os.startfile(shortcut_path, cwd=os.environ.get("TEMP", os.getcwd()))
    deadline = time.monotonic() + 20.0
    target = None
    while time.monotonic() < deadline:
        for hwnd, pid, title in _visible_archetexture_windows():
            if pid not in baseline_pids:
                target = (hwnd, pid, title)
                break
        if target:
            break
        time.sleep(0.1)
    if not target:
        raise SystemExit("The desktop shortcut did not open a visible main window.")

    hwnd, pid, title = target
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.WaitForSingleObject.restype = ctypes.c_ulong
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    ctypes.windll.user32.SendMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    process = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)
    if not process:
        raise SystemExit(f"Could not inspect launched GUI process {pid}.")
    try:
        image = ctypes.create_unicode_buffer(32768)
        image_size = ctypes.c_ulong(len(image))
        if not kernel32.QueryFullProcessImageNameW(process, 0, image, ctypes.byref(image_size)):
            raise SystemExit("Could not resolve the launched GUI executable.")
        if os.path.basename(image.value).casefold() != "pythonw.exe":
            raise SystemExit(f"Launcher used an unexpected process: {image.value}")
        ctypes.windll.user32.SendMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        wait_result = kernel32.WaitForSingleObject(process, 15000)
        if wait_result != 0:
            raise SystemExit("The launched application did not close cleanly after WM_CLOSE.")
    finally:
        kernel32.CloseHandle(process)
    print(f"Desktop shortcut from outside checkout: opened {title!r} in pythonw.exe and closed cleanly")


class MemorySettings:
    def value(self, _key: str, default=None):
        return default

    def setValue(self, _key: str, _value) -> None:
        pass

    def sync(self) -> None:
        pass


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("This acceptance check must run on Windows.")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    verify_repo_launcher(repo_root)

    app = QApplication(["ArcheTexture launcher acceptance"])
    app.setOrganizationName("ArcheTexture Acceptance")
    app.setApplicationName("Launcher Smoke")
    MainWindow._theme_settings = staticmethod(MemorySettings)

    if app.platformName().casefold() != "windows":
        raise SystemExit(f"Unexpected Qt platform: {app.platformName()}")
    window = MainWindow()
    window._confirm_discard = lambda: True
    window.show()
    app.processEvents()
    if not window.isVisible():
        raise SystemExit("Main window did not become visible.")
    if window.workspace_mode_combo.currentData() != "2D Texture":
        raise SystemExit("The default 2D workspace did not initialize.")
    if window.workspace_stack.currentWidget() is not window.viewport:
        raise SystemExit("The 2D texture viewport is not active.")
    if window.viewport.width() <= 0 or window.viewport.height() <= 0:
        raise SystemExit("The 2D viewport has no drawable size.")
    if window.new_from_material_action.text() != "New from Material…":
        raise SystemExit("File → New from Material… is missing.")

    dialog = MaterialStarterDialog(window)
    expected = {starter.name for starter in MATERIAL_STARTERS}
    actual = {
        dialog.material_list.item(index).text()
        for index in range(dialog.material_list.count())
    }
    if len(expected) != 18 or actual != expected:
        raise SystemExit(f"Material catalog mismatch: expected 18, found {len(actual)}.")
    dialog.close()

    window.workspace_mode_combo.setCurrentIndex(
        window.workspace_mode_combo.findData("3D Material")
    )
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        app.processEvents()
        if window.preview_viewport.available or window.preview_viewport._gl_error:
            break
        time.sleep(0.025)
    if window.preview_viewport.available:
        preview_result = "3D OpenGL preview initialized"
    elif window.preview_viewport._gl_error:
        if window.workspace_stack.currentWidget() is not window.preview_unavailable_label:
            raise SystemExit("3D OpenGL failed without showing its fallback message.")
        if not window.preview_unavailable_label.text().strip():
            raise SystemExit("3D OpenGL fallback message is empty.")
        preview_result = "3D OpenGL unavailable; graceful fallback displayed"
    else:
        raise SystemExit("3D preview neither initialized nor reported its fallback.")

    window.close()
    app.processEvents()
    if window.isVisible():
        raise SystemExit("Main window did not close cleanly.")
    print(f"Qt platform: {app.platformName()}")
    print("2D workspace: initialized and visible")
    print(f"3D preview: {preview_result}")
    print("File menu New from Material action: present")
    print("Material starter catalog: all 18 present")
    print("Main window: closed cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
