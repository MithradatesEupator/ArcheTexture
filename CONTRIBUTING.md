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
