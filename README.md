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
  compositing. Output reference generators can derive live scalar and color
  fields from another output by stable output ID. Scalar extraction supports
  Direct, luminance, RGB, alpha, average, minimum, and maximum modes. The
  Output Manager includes derived workflows such as Normal from Height,
  reciprocal Roughness and Glossiness, Base Color Alpha to Opacity, and custom
  scalar or color outputs. Normal from Height remains an ordinary editable
  pipeline, so changing Height updates Normal. Renaming and reordering outputs
  preserve references. Dependency cycles are rejected, Control Fields cannot
  reference material outputs in this release, and deleting a referenced output
  is blocked with its dependents listed. Texture-set export renders hidden
  upstream dependencies internally while writing only selected maps. Normal
  layers still use ordinary image blending, not vector-correct normal blending.

Texture-set export writes separate semantic maps and supports ORM, RMA, MRA,
Unity HDRP-like mask packing, and custom RGBA channel packs. Missing packing
sources fail preflight instead of being silently substituted. Scalar maps can
be exported as 8-bit or 16-bit grayscale PNG; color and normal maps use 8-bit
RGBA PNG. Semantic labels describe the data channel and do not claim
renderer-specific physical fidelity.

The unreleased workspace also has an interactive 3D material preview. It
offers UV sphere, cube, plane, cylinder, torus, and rounded-cube meshes, three
mesh qualities, orbit/pan/zoom camera controls, perspective and orthographic
projection, UV tiling and rotation, and a compact metallic/roughness PBR
display. Output bindings use stable material output IDs and can be overridden
in the Preview tab without changing the material graph. Preview snapshots are
rendered asynchronously through the multi-output renderer; view-only changes
do not request new material maps. Preview preferences are stored in user
settings and do not dirty a project. The preview requests desktop OpenGL 3.3
Core; systems without a compatible context retain the full 2D workflow and
show an in-app unavailable message. The renderer is an inspection aid, not a
renderer-accurate or color-managed PBR reference.

The unreleased procedural library adds ridged and billow multifractals,
gradient and domain-warped noise, expanded Voronoi distance choices, and
architecture, organic, and textile patterns such as masonry, honeycomb,
Truchet tiles, wood rings, marble veins, polka dots, radial rings and spokes,
weave, and crosshatch. Scalar transforms now include range and power remaps,
terracing, smoothstep, directional blur, emboss, high-pass, morphology,
coordinate warps, polar and symmetry mappings, pixelation, and edge filters.
Source and transform selectors provide category-aware searchable filtering.

File → **New from Material…** opens a searchable collection of 18 editable
recipes, including stone, marble, concrete, brick, metals, woods, textiles,
ceramic, soil, rock, sci-fi panels, and organic surfaces. Each recipe builds
Base Color, Roughness, Metallic, Normal, Height, and Ambient Occlusion outputs
from procedural fields. Shared Scale and Wear Control Fields modulate the
recipe, and Normal, Roughness, and AO stay linked to the live Height output.
These are artistic starting points, not physically measured materials.

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

The interface is organized around a layer and transform workspace, switchable
2D Texture and 3D Material central modes, a color ramp, and Properties, Control
Fields, or Preview tabs.

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

The published version 0.1.0 is an early development alpha and does not contain
the unreleased multi-output, procedural-library, or 3D preview work. Some
generators and operations are not seamless, and the seam status is advisory.
Normal-map layers use
regular image blend modes, which do not perform physically correct vector
blending. The 3D preview uses a compact desktop OpenGL shader; parallax height,
HDR/EXR, professional color management, and renderer-perfect matching are not
provided. ArcheTexture does not include a node editor, GPU procedural
generation, or a general-purpose installer.

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
