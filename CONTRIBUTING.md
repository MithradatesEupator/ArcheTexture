# Contributing

## Setup and checks

Use Python 3.12 or later, create a virtual environment, and install the project
with its development tools:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Before submitting a change, run `ruff check .`, `ruff format --check .`,
`python -m pytest`, and `python -m pip check`. CI runs these checks on Ubuntu
and Windows with Python 3.12. Package changes should also pass
`python -m build` and the installed-package acceptance script.

## Design principles

Keep domain recipes independent of Qt widgets. The GUI gathers edits and
displays results; algorithms belong in registered operations and reusable core
modules. Register generators and transforms through operation metadata rather
than adding special cases to the orchestration pipeline. Preserve schema
migrations and test each operation's numeric behavior, validation, serialization,
and relevant UI integration. Changes to cache dependencies require tests proving
both invalidation and reuse.

Work on a focused branch based on the current project branch. Avoid committing
generated builds, local environments, caches, or benchmark output unless a
specific artifact is intentionally part of the change.

## Interim contribution policy

Bug reports, feature requests, technical discussion, and testing reports are
welcome. At this stage, outside pull requests containing copyrightable code,
documentation, artwork, or other substantive contributed material will not be
merged until an explicit contributor-rights arrangement compatible with the
project's dual-licensing strategy has been established. ArcheTexture is publicly
licensed under GPL-3.0-only, while the project owner wishes to preserve the
option of separately negotiated commercial licenses. This policy avoids
implying that contributors have granted rights needed for that separate
licensing. No copyright assignment or contributor agreement is being adopted
here.
