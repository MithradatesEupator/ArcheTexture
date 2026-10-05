# ArcheTexture

ArcheTexture is an early-development procedural texture workstation. It uses a
linear recipe to generate a scalar field, apply transforms, and display the
result as RGBA pixels. The project is not release-ready, but the initial
desktop workflow is functional and covered by automated tests.

## Current workflow

- Start with a deterministic, colorized white-noise recipe.
- Select Constant, White Noise, Linear Gradient, or Radial Gradient as the
  source.
- Add, configure, enable, disable, reorder, and remove Invert, Threshold, and
  Quantize transforms.
- Render on a background worker while the Qt interface remains responsive.
- Undo and redo recipe edits.
- Save and reopen human-readable `.archetexture` JSON project files.
- Keep normalized float32 scalar output for computation and apply the optional
  color ramp at the RGBA display boundary.

Control fields can be represented, validated, serialized, and bound to numeric
operation parameters. This first workbench does not yet include a graphical
control-field or color-ramp editor.

## Run the application

Use Python 3.12 or later:

```bash
python -m venv .venv
```

Activate the environment, then install and launch:

```bash
python -m pip install -e '.[dev]'
python -m archetexture
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`; on
Linux/macOS, use `source .venv/bin/activate`. The application selects the
platform's normal Qt display backend. Headless testing configures Qt offscreen
through the test setup and CI environment.

## Development checks

```bash
ruff check .
ruff format --check .
python -m pytest
```

Continuous integration runs these checks on Ubuntu and Windows with Python
3.12.

## Architecture

- The declarative `ProjectRecipe` is the document. Render buffers, Qt widgets,
  and worker state are derived runtime data and are never saved in a project.
- Operation registrations connect stable IDs and versions, parameter and field
  metadata, seamlessness declarations, and implementation callables.
- The pipeline executes the registered implementations in source-to-transform
  order. Generators and transforms live outside the orchestration layer.
- Control fields use named references and the same operation pipeline; cycles
  and incompatible references are rejected during validation.
- A single background render worker coalesces pending work and publishes only
  the newest request result or error.
- History stores deep recipe snapshots, so edits cannot mutate older states and
  edits after undo discard the old redo branch.
- Project files use explicit schema-versioned JSON encoding and reconstruct
  domain objects on load.

## Dependency policy and limitations

Runtime and development dependencies are declared in `pyproject.toml`. There is
no lockfile; installs resolve versions allowed by the declared minimum ranges.
Dependency locking is deferred to a dedicated packaging phase rather than
adding another packaging system in this work.

ArcheTexture currently has a small operation set, no graphical control-field
or ramp editing, and no advanced seamless synthesis, node graph, layers, GPU
acceleration, or packaged installer. These are future development areas, not
implemented features.
