# ArcheTexture

ArcheTexture is an early-development desktop workstation for building
procedural textures from editable layers. It combines generators, transforms,
masks, color ramps, and parameter modulation in a project that can be saved as
readable JSON and exported as PNG. The current multi-output development branch
adds material channels and texture-set export; these features were not part of
the published 0.1.0 binary.

## What it can do

### Unreleased multi-output material workflow

The ongoing development workspace stores one or more material outputs, each
with its own layer stack. A semantic registry groups Base Color, Roughness,
Metallic, Normal, Height, Ambient Occlusion, Emissive, legacy/specular,
advanced, utility, and custom color/scalar outputs. Control Fields remain
project-global and can drive layers in multiple outputs. Material presets add
missing channels without replacing existing work.

Scalar outputs keep normalized float32 values through compositing and export;
their viewport representation is grayscale. Color outputs retain RGBA
compositing. Normal outputs require RGBA-producing layers, with Height to
Normal as the supported procedural path. Normal layers still use ordinary
image blending, not vector-correct normal blending. Outputs do not yet have
live references to one another; copying or moving a pipeline creates an
independent layer stack.

Texture-set export writes separate semantic maps and supports ORM, RMA, MRA,
Unity HDRP-like mask packing, and custom RGBA channel packs. Missing packing
sources fail preflight instead of being silently substituted. Scalar maps can
be exported as 8-bit or 16-bit grayscale PNG; color and normal maps use 8-bit
RGBA PNG. Semantic labels describe the data channel and do not claim
renderer-specific physical fidelity.

- Build a procedural layer stack with opacity, blend modes, and ordered
  transforms.
- Use noise, patterns, cellular, image, and seamless generators.
- Color scalar fields with editable ramps; generate tangent-space normal maps
  from height fields.
- Reuse Control Fields to modulate compatible parameters and transform
  influence; use procedural or image-derived layer masks.
- Preview a single tile, a 3×3 tile view, or a seam check.
- Import external images, keep project-relative references, and save or reopen
  `.archetexture` project files.
- Undo and redo edits, choose project dimensions and a global seed, and export
  lossless RGBA PNGs.
- Render asynchronously with dependency-aware caches. Choose dark, light, or
  system appearance.

The interface is organized around a layer and transform workspace, a central
texture viewport and color ramp, and Properties or Control Fields tabs.

## Running ArcheTexture

ArcheTexture requires Python 3.12 or later. Version 0.1.0 is the current
public alpha. The Windows portable bundle is distributed through the GitHub
Release; it is unsigned and is not an installer. Treat alpha builds as
experimental.

To run from source, create and activate a virtual environment, then install the
application:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install .
archetexture
```

The module invocation is also supported: `python -m archetexture`. On Linux or
macOS, activate with `source .venv/bin/activate`. The application is a local
desktop program and does not need network access for normal operation.

## Developer setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m archetexture
```

Run the quality checks with:

```text
ruff check .
ruff format --check .
python -m pytest
python -m pip check
```

Package installation and build instructions are in [CONTRIBUTING.md](CONTRIBUTING.md).
CI tests Python 3.12 on Ubuntu and Windows, and validates built packages.

## Projects and assets

Project files are JSON documents with an explicit schema version. The released
0.1.0 format was schema v4. The current multi-output development format is
schema v5; versions v1 through v4 migrate when opened. Legacy
projects become one Custom Color output to preserve their prior rendered
meaning. Render buffers and worker state are derived and are not saved. Images
remain external assets: references can be absolute or relative to the project file, so a project and
its asset directory can be moved together. Image pixels are not embedded in
project files.

## Development status and limitations

The published version 0.1.0 is an early development alpha. Some generators and operations
are not seamless, and the seam status is advisory. Normal-map layers use the
regular image blend modes, which do not perform physically correct vector
blending. The developing material workflow has no live output-to-output
dependencies, HDR/EXR, professional color management, or 3D material preview.
ArcheTexture does not include a node editor, GPU acceleration, or a
general-purpose installer.

## License

ArcheTexture is distributed under the GNU General Public License version 3.0
only (`GPL-3.0-only`); see [LICENSE](LICENSE). The GPL permits commercial use
under its terms. Using ArcheTexture to create an image does not, by itself,
automatically place that generated image under the GPL; the GPL governs
ArcheTexture and derivatives within the license's scope, and image rights may
also depend on incorporated material and other applicable rules.

Organizations that need rights the GPL does not grant, such as proprietary
redistribution of ArcheTexture or incorporating its code into a distributed
closed-source derivative, may contact the copyright holder to discuss a
separate commercial license. This is an optional, separately negotiated
arrangement; no prices or terms are published here.

Runtime dependencies are NumPy, Pillow, and PySide6. Development and build
tools are optional dependencies, not runtime requirements. The project uses
minimum version constraints and does not yet have a lockfile. There is no
telemetry, analytics, update checker, cloud sync, or network service.

See [CHANGELOG.md](CHANGELOG.md) for a short feature history and
[SECURITY.md](SECURITY.md) for reporting security issues.
