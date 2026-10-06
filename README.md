# ArcheTexture

ArcheTexture is an early-development procedural texture workstation. It uses a
layered recipe to generate scalar fields, apply transforms, composite layers,
and display the result as RGBA pixels. The desktop workflow is functional and
covered by automated tests, but the project is not release-ready.

## Current workflow

- Start with a colorized, layered Fractal Noise composition.
- Choose from constant, gradient, noise, periodic noise, cellular, bands, and
  checker/grid sources.
- Add, configure, enable, disable, reorder, and remove tonal, spatial, and
  detail transforms.
- Inspect the viewport in Single, Tile 3×3, or Seam Check mode. These are
  presentation modes and do not change the project recipe or PNG output.
- Render on a background worker while the Qt interface remains responsive.
- Undo and redo recipe edits.
- Save and reopen human-readable `.archetexture` JSON project files.
- Export the current recipe snapshot as a lossless 8-bit RGBA PNG at the
  project dimensions or an independently chosen size from 1 to 8192 pixels.
- Keep normalized float32 scalar output for computation and apply the optional
  color ramp at the RGBA display boundary. Display and PNG output share the
  same clipped, rounded 8-bit channel conversion.

Control fields are reusable scalar recipes with a generator source, ordered
transform chain, and optional normalized global mapping. Create and manage them
in the Control Fields tab, then bind them to compatible numeric parameters or
transform Influence from Properties. Each binding has its own output range,
invert, curve, and optional quantization settings. Rename updates references;
deletion is blocked while a field is in use. Cyclic control-field references
are rejected before a document edit is committed. Nested control-field
references can be edited through the same property controls, but there is no
dependency-graph view or standalone control-field preview. The graphical
color-ramp editor remains beneath the main viewport. The selected viewport
mode is an application preference and remains selected when creating or
opening projects.

## Seamless synthesis

Seamless Value Noise, Seamless Fractal Noise, Seamless Turbulence, and Seamless
Cellular generate periodic scalar fields. Their integer Cells X and Cells Y
parameters define the tile's lattice period independently of output resolution.
Fractal and turbulence octaves multiply both periods by an integer lacunarity
(2, 3, or 4), so every octave remains periodic. Cellular feature hashes wrap
by those cell periods and distance search considers neighboring periodic cell
images. Existing non-seamless generators retain their original behavior.

Tile 3×3 draws the already-rendered tile nine times. Seam Check shifts the
display by half the tile width and height, bringing the original boundaries to
the center for visual inspection. Neither mode changes the render, saved
recipe, or single-tile PNG export.

The `Seamless: Yes / No / Unknown` indicator is conservative. It combines
enabled, visible layers and their transform metadata; Checker / Grid is
conditional (grid lines repeat, while checker cells require even counts on
both axes). Spatially modulated parameters and operations with unknown
behavior prevent a Yes result. This indicator is advisory; the procedural
sampling functions are covered by numeric periodicity tests. Not every source
or operation is seamless, and native/manual Windows acceptance remains
separate from the automated test suite.

PNG export preserves alpha and writes atomically, replacing an existing file
only after a complete image is ready. PNG is the only image export format. No
gamma conversion or color profile management is applied. Dimensions above
4096 pixels produce a warning in the export dialog.

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

ArcheTexture remains in early development. Non-periodic generators and
operations with unknown seamlessness can still introduce visible boundaries;
the status indicator does not attempt to prove cancellation between such
operations. There is no node graph, GPU acceleration, or packaged installer.
