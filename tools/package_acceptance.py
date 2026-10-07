"""Exercise a built, installed ArcheTexture package without source-path imports."""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile
from pathlib import Path

from PIL import Image

import archetexture
from archetexture.core.defaults import default_recipe
from archetexture.core.serialization import load_project, save_project
from archetexture.export.image_export import ImageExporter
from archetexture.render.engine import RenderEngine


def _assert_distribution_licenses(dist: Path, repo: Path) -> None:
    wheels = list(dist.glob("archetexture-*.whl"))
    sdists = list(dist.glob("archetexture-*.tar.gz"))
    assert len(wheels) == 1, f"Expected one wheel in {dist}, found {len(wheels)}"
    assert len(sdists) == 1, f"Expected one source archive in {dist}, found {len(sdists)}"
    license_bytes = (repo / "LICENSE").read_bytes()
    metadata = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert metadata["license"] == "GPL-3.0-only"
    assert metadata["license-files"] == ["LICENSE"]

    with tarfile.open(sdists[0], "r:gz") as source:
        license_members = [member for member in source.getnames() if member.endswith("/LICENSE")]
        assert len(license_members) == 1
        assert source.extractfile(license_members[0]).read() == license_bytes

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        info_dir = next(
            name.split("/")[0] for name in names if name.endswith(".dist-info/METADATA")
        )
        license_path = f"{info_dir}/licenses/LICENSE"
        assert license_path in names
        assert wheel.read(license_path) == license_bytes
        package_metadata = wheel.read(f"{info_dir}/METADATA").decode("utf-8")
        assert "License-Expression: GPL-3.0-only" in package_metadata
        assert "License-File: LICENSE" in package_metadata


def _assert_wheel_contents(dist: Path) -> None:
    wheels = list(dist.glob("archetexture-*.whl"))
    assert len(wheels) == 1, f"Expected one wheel in {dist}, found {len(wheels)}"
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        assert "archetexture/__main__.py" in names
        assert "archetexture/ui/main_window.py" in names
        assert not any(name.startswith(("tests/", "tools/")) for name in names)


def _smoke_entry_point(command: list[str], cwd: Path) -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("PYTHONPATH", None)
    process = subprocess.Popen(command, cwd=cwd, env=env)
    try:
        time.sleep(4)
        if process.poll() is not None:
            raise RuntimeError(
                f"Application entry point exited early: {command} ({process.returncode})"
            )
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    dist = Path(os.environ.get("ARCHETEXTURE_DIST_DIR", repo / "dist"))
    _assert_wheel_contents(dist)
    _assert_distribution_licenses(dist, repo)
    readme = (repo / "README.md").read_text(encoding="utf-8")
    assert "GPL-3.0-only" in readme
    assert "GPL-3.0-or-later" not in readme
    assert archetexture.__version__ == "0.1.0"
    assert "site-packages" in str(Path(archetexture.__file__).resolve()).lower()

    with tempfile.TemporaryDirectory(
        prefix="archetexture-wheel-smoke-", ignore_cleanup_errors=True
    ) as temp:
        work = Path(temp)
        recipe = default_recipe()
        recipe.width = 48
        recipe.height = 40
        result = RenderEngine().render(recipe)
        assert result.rgba_field.shape == (40, 48, 4)
        project_path = work / "acceptance.archetexture"
        save_project(recipe, project_path)
        reopened = load_project(project_path)
        assert reopened.schema_version == 4
        assert reopened.width == 48 and reopened.height == 40
        image_path = work / "acceptance.png"
        ImageExporter().export_png(reopened, image_path)
        with Image.open(image_path) as image:
            image.load()
            assert image.format == "PNG" and image.mode == "RGBA"
            assert image.size == (48, 40)
            assert image.getbbox() is not None
            assert image.getchannel("R").getextrema()[0] < image.getchannel("R").getextrema()[1]

        scripts = Path(sys.executable).parent
        if os.name == "nt":
            console = scripts / "archetexture.exe"
        else:
            console = scripts / "archetexture"
        assert console.exists(), f"Installed console entry point not found: {console}"
        _smoke_entry_point([str(console)], work)
        _smoke_entry_point([sys.executable, "-m", "archetexture"], work)
    print(
        "Built wheel, sdist, installed import, render/save/reopen/PNG export, "
        "and both entry points passed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
