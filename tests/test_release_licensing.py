from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_project_declares_gpl_only_and_canonical_license_file():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    assert project["license"] == "GPL-3.0-only"
    assert project["license-files"] == ["LICENSE"]
    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 29 June 2007" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text


def test_public_license_and_output_terms_do_not_claim_gpl_or_later():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "GPL-3.0-only" in readme
    assert "commercial use" in readme
    assert "does not, by itself" in readme
    assert "GPL-3.0-or-later" not in readme
    assert "MIT License" not in readme
    assert "Apache License" not in readme


def test_interim_policy_welcomes_reports_but_defers_substantive_external_patches():
    policy = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "Bug reports, feature requests, technical discussion, and testing reports" in policy
    assert "outside pull requests containing copyrightable code" in policy
    assert "contributor-rights arrangement" in policy
    assert "No copyright assignment or contributor agreement" in policy
