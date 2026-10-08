"""Built-in expanded procedural operation definitions."""

from __future__ import annotations

from archetexture.core.operations import OperationDefinition, OperationType, Seamlessness
from archetexture.core.parameters import ParameterSpec, ParameterType
from archetexture.generators import expanded as generators
from archetexture.transforms import expanded as transforms


def _p(
    identifier, name, kind, default, minimum=None, maximum=None, step=None, *, options=(), mod=True
):
    return ParameterSpec(
        identifier,
        name,
        kind,
        default,
        minimum,
        maximum,
        step,
        allows_modulation=mod,
        options=tuple(options),
    )


def _definition(
    identifier,
    name,
    category,
    description,
    output,
    specs,
    implementation,
    *,
    seamless=Seamlessness.UNKNOWN,
    context=False,
):
    operation_type = (
        OperationType.GENERATOR if identifier.startswith("generator.") else OperationType.TRANSFORM
    )
    input_types = () if operation_type == OperationType.GENERATOR else ("scalar",)
    return OperationDefinition(
        identifier,
        1,
        name,
        category,
        description,
        operation_type,
        input_types,
        output,
        tuple(specs),
        seamless,
        implementation,
        requires_render_context=context,
    )


F = ParameterType.FLOAT
INT = ParameterType.INTEGER
E = ParameterType.ENUM
B = ParameterType.BOOLEAN
SEED = ParameterType.SEED


def expanded_definitions() -> tuple[OperationDefinition, ...]:
    def seed(value=101):
        return _p("seed", "Seed", SEED, value, 0, 2**31 - 1, 1, mod=False)

    def scale(value=5.0, upper=48.0):
        return _p("scale", "Scale", F, value, 0.25, upper, 0.25)

    def offset_x():
        return _p("offset_x", "Offset X", F, 0.0, -20.0, 20.0, 0.1)

    def offset_y():
        return _p("offset_y", "Offset Y", F, 0.0, -20.0, 20.0, 0.1)

    def rotation():
        return _p("rotation", "Rotation", ParameterType.ANGLE, 0.0, 0.0, 360.0, 1.0)

    octave_specs = (
        _p("octaves", "Octaves", INT, 5, 1, 10, 1, mod=False),
        _p("lacunarity", "Lacunarity", F, 2.0, 1.1, 4.0, 0.1, mod=False),
        _p("persistence", "Persistence", F, 0.5, 0.0, 0.95, 0.05, mod=False),
    )

    def common_noise(default=5.0):
        return (seed(), scale(default), *octave_specs, rotation(), offset_x(), offset_y())

    definitions = [
        _definition(
            "generator.ridged_noise",
            "Ridged Multifractal",
            "Noise",
            "Layered inverted absolute noise for sharp ridges and crags.",
            "scalar",
            common_noise(4.0),
            generators.ridged_noise,
            context=True,
        ),
        _definition(
            "generator.billow_noise",
            "Billow Noise",
            "Noise",
            "Layered folded noise with rounded, billowing forms.",
            "scalar",
            common_noise(4.0),
            generators.billow_noise,
            context=True,
        ),
        _definition(
            "generator.perlin_noise",
            "Gradient Noise",
            "Noise",
            "Deterministic gradient-lattice noise with smooth Perlin-style interpolation.",
            "scalar",
            (seed(), scale(), rotation(), offset_x(), offset_y()),
            generators.perlin_noise,
        ),
        _definition(
            "generator.domain_warp",
            "Domain Warped Noise",
            "Noise",
            "Bends the sampling domain with two deterministic noise fields.",
            "scalar",
            (
                seed(),
                scale(3.0),
                _p("frequency", "Feature Frequency", F, 2.5, 0.25, 32.0, 0.25),
                _p("warp_scale", "Warp Scale", F, 2.0, 0.25, 24.0, 0.25),
                _p("warp_amount", "Warp Amount", F, 1.5, 0.0, 8.0, 0.1),
                rotation(),
            ),
            generators.domain_warp,
            context=True,
        ),
        _definition(
            "generator.brick",
            "Brick / Masonry",
            "Architecture",
            "Offset masonry courses with editable mortar, jitter, and variation.",
            "scalar",
            (
                _p("columns", "Columns", INT, 8, 1, 128, 1, mod=False),
                _p("rows", "Rows", INT, 6, 1, 128, 1, mod=False),
                _p("mortar", "Mortar Width", F, 0.06, 0.0, 0.25, 0.01),
                _p("jitter", "Jitter", F, 0.04, 0.0, 0.4, 0.01),
                _p("variation", "Brick Variation", F, 0.18, 0.0, 0.5, 0.01),
                offset_x(),
                offset_y(),
            ),
            generators.brick,
        ),
        _definition(
            "generator.hex_cells",
            "Hex / Honeycomb",
            "Patterns",
            "Honeycomb cells with adjustable density and recessed edges.",
            "scalar",
            (
                _p("density", "Density", F, 9.0, 1.0, 64.0, 1.0),
                _p("edge_width", "Edge Width", F, 0.08, 0.0, 0.45, 0.01),
            ),
            generators.hex_cells,
        ),
        _definition(
            "generator.truchet",
            "Truchet Tiles",
            "Patterns",
            "Seeded quarter-arc tile orientations for repeatable ornamental fields.",
            "scalar",
            (
                seed(),
                _p("density", "Tile Density", F, 8.0, 1.0, 64.0, 1.0),
                _p("line_width", "Line Width", F, 0.08, 0.01, 0.35, 0.01),
            ),
            generators.truchet,
        ),
        _definition(
            "generator.wood_rings",
            "Wood Rings",
            "Organic",
            "Concentric wood grain with seeded distortion and ring spacing.",
            "scalar",
            (
                seed(),
                _p("rings", "Ring Frequency", F, 26.0, 1.0, 128.0, 1.0),
                _p("distortion", "Distortion Scale", F, 7.0, 0.25, 48.0, 0.25),
                _p("warp", "Warp Amount", F, 0.25, 0.0, 2.0, 0.01),
                _p("center_x", "Center X", F, 0.0, -1.0, 1.0, 0.01),
                _p("center_y", "Center Y", F, 0.0, -1.0, 1.0, 0.01),
            ),
            generators.wood_rings,
            context=True,
        ),
        _definition(
            "generator.marble_veins",
            "Marble / Veins",
            "Organic",
            "Warped directional bands resembling natural mineral veins.",
            "scalar",
            (
                seed(),
                scale(3.0),
                _p("vein_frequency", "Vein Frequency", F, 12.0, 1.0, 64.0, 0.5),
                _p("distortion", "Distortion", F, 3.0, 0.0, 12.0, 0.1),
                _p("octaves", "Octaves", INT, 4, 1, 8, 1, mod=False),
                rotation(),
            ),
            generators.marble_veins,
            context=True,
        ),
        _definition(
            "generator.polka_dots",
            "Dots / Polka",
            "Patterns",
            "Regular or staggered dots with optional deterministic positional jitter.",
            "scalar",
            (
                seed(),
                _p("columns", "Columns", INT, 12, 1, 128, 1, mod=False),
                _p("rows", "Rows", INT, 12, 1, 128, 1, mod=False),
                _p("radius", "Dot Radius", F, 0.28, 0.03, 0.49, 0.01),
                _p("jitter", "Jitter", F, 0.0, 0.0, 0.45, 0.01),
                _p("stagger", "Stagger Rows", B, True),
            ),
            generators.dots,
        ),
        _definition(
            "generator.concentric_rings",
            "Concentric Rings",
            "Patterns",
            "Circular ring fields with line and sinusoidal modes.",
            "scalar",
            (
                _p("frequency", "Frequency", F, 18.0, 1.0, 128.0, 1.0),
                _p("line_width", "Line Width", F, 0.12, 0.01, 0.5, 0.01),
                _p("center_x", "Center X", F, 0.0, -1.0, 1.0, 0.01),
                _p("center_y", "Center Y", F, 0.0, -1.0, 1.0, 0.01),
                _p("mode", "Mode", E, "lines", options=("lines", "sine")),
            ),
            generators.concentric_rings,
        ),
        _definition(
            "generator.radial_spokes",
            "Radial Spokes",
            "Patterns",
            "Radially repeated spokes with rotation and center fade controls.",
            "scalar",
            (
                _p("spokes", "Spokes", INT, 16, 2, 128, 1, mod=False),
                rotation(),
                _p("center_fade", "Center Fade", F, 0.12, 0.0, 0.8, 0.01),
            ),
            generators.radial_spokes,
        ),
        _definition(
            "generator.weave",
            "Weave / Textile",
            "Textile",
            "Interlaced warp and weft threads with alternating over-under structure.",
            "scalar",
            (
                seed(),
                _p("threads_x", "Threads X", INT, 14, 1, 128, 1),
                _p("threads_y", "Threads Y", INT, 14, 1, 128, 1),
                _p("thread_width", "Thread Width", F, 0.32, 0.05, 0.48, 0.01),
                _p("variation", "Variation", F, 0.1, 0.0, 0.4, 0.01),
            ),
            generators.weave,
        ),
        _definition(
            "generator.crosshatch",
            "Crosshatch",
            "Textile",
            "Single or crossed diagonal strokes with configurable angle and spacing.",
            "scalar",
            (
                _p("frequency", "Frequency", F, 14.0, 1.0, 96.0, 1.0),
                rotation(),
                _p("line_width", "Line Width", F, 0.08, 0.01, 0.3, 0.01),
                _p("single_direction", "Single Direction", B, False),
            ),
            generators.crosshatch,
        ),
        _definition(
            "transform.clamp_range",
            "Clamp / Range",
            "Tone",
            "Remaps a selected source interval to the full normalized range.",
            "scalar",
            (
                _p("input_min", "Input Minimum", F, 0.1, 0.0, 1.0, 0.01),
                _p("input_max", "Input Maximum", F, 0.9, 0.0, 1.0, 0.01),
            ),
            transforms.clamp_range,
            seamless=Seamlessness.PRESERVES,
        ),
        _definition(
            "transform.gamma",
            "Power / Gamma",
            "Tone",
            "Applies a direct power curve to normalized values.",
            "scalar",
            (_p("power", "Power", F, 1.0, 0.05, 8.0, 0.05),),
            transforms.gamma,
            seamless=Seamlessness.PRESERVES,
        ),
        _definition(
            "transform.sine_remap",
            "Sine Remap",
            "Tone",
            "Cycles source values through sine, triangle, or square waves.",
            "scalar",
            (
                _p("cycles", "Cycles", F, 1.0, 0.25, 16.0, 0.25),
                _p("phase", "Phase", F, 0.0, -1.0, 1.0, 0.01),
                _p("mode", "Wave", E, "sine", options=("sine", "triangle", "square")),
            ),
            transforms.sine_remap,
            seamless=Seamlessness.PRESERVES,
        ),
        _definition(
            "transform.fold",
            "Absolute / Fold",
            "Tone",
            "Folds scalar values around a selectable center line.",
            "scalar",
            (
                _p("center", "Center", F, 0.5, 0.0, 1.0, 0.01),
                _p("amount", "Amount", F, 2.0, 0.0, 8.0, 0.05),
            ),
            transforms.fold,
            seamless=Seamlessness.PRESERVES,
        ),
        _definition(
            "transform.terrace",
            "Terrace / Steps",
            "Tone",
            "Creates discrete levels with controllable smoothing between steps.",
            "scalar",
            (
                _p("steps", "Steps", INT, 6, 2, 64, 1),
                _p("smoothness", "Smoothness", F, 0.0, 0.0, 1.0, 0.01),
            ),
            transforms.terrace,
            seamless=Seamlessness.PRESERVES,
        ),
        _definition(
            "transform.smoothstep",
            "Smoothstep",
            "Tone",
            "Softly remaps values between two edges using cubic interpolation.",
            "scalar",
            (
                _p("edge0", "Edge 0", F, 0.2, 0.0, 1.0, 0.01),
                _p("edge1", "Edge 1", F, 0.8, 0.0, 1.0, 0.01),
            ),
            transforms.smoothstep,
            seamless=Seamlessness.PRESERVES,
        ),
        _definition(
            "transform.directional_blur",
            "Directional Blur",
            "Detail",
            "Wrap-safe motion blur along a chosen pixel direction.",
            "scalar",
            (_p("radius", "Radius", INT, 3, 1, 16, 1, mod=False), rotation()),
            transforms.directional_blur,
            seamless=Seamlessness.PRESERVES,
            context=True,
        ),
        _definition(
            "transform.emboss",
            "Emboss",
            "Detail",
            "Relief shading from wrapped central differences and a light angle.",
            "scalar",
            (
                _p("strength", "Strength", F, 3.0, 0.0, 16.0, 0.1),
                _p("light_angle", "Light Angle", ParameterType.ANGLE, 315.0, 0.0, 360.0, 1.0),
            ),
            transforms.emboss,
            seamless=Seamlessness.PRESERVES,
        ),
        _definition(
            "transform.high_pass",
            "High-pass",
            "Detail",
            "Extracts local detail by subtracting a wrapped Gaussian low-pass.",
            "scalar",
            (
                _p("radius", "Radius", F, 2.0, 0.1, 12.0, 0.1, mod=False),
                _p("gain", "Gain", F, 4.0, 0.1, 16.0, 0.1),
            ),
            transforms.high_pass,
            seamless=Seamlessness.PRESERVES,
            context=True,
        ),
        _definition(
            "transform.dilate",
            "Dilate",
            "Morphology",
            "Expands brighter regions with a wrap-safe square neighborhood.",
            "scalar",
            (_p("radius", "Radius", INT, 1, 1, 12, 1, mod=False),),
            transforms.dilate,
            seamless=Seamlessness.PRESERVES,
            context=True,
        ),
        _definition(
            "transform.erode",
            "Erode",
            "Morphology",
            "Shrinks brighter regions with a wrap-safe square neighborhood.",
            "scalar",
            (_p("radius", "Radius", INT, 1, 1, 12, 1, mod=False),),
            transforms.erode,
            seamless=Seamlessness.PRESERVES,
            context=True,
        ),
        _definition(
            "transform.warp",
            "Warp / Displace",
            "Spatial",
            "Offsets coordinates with two modulated displacement fields.",
            "scalar",
            (
                _p("offset_x", "Offset X", F, 0.0, -1.0, 1.0, 0.005),
                _p("offset_y", "Offset Y", F, 0.0, -1.0, 1.0, 0.005),
            ),
            transforms.warp,
        ),
        _definition(
            "transform.swirl",
            "Swirl",
            "Spatial",
            "Twists coordinates around the image center with radial falloff.",
            "scalar",
            (
                _p("angle", "Angle", ParameterType.ANGLE, 180.0, -720.0, 720.0, 1.0),
                _p("radius", "Radius", F, 0.5, 0.01, 1.0, 0.01),
            ),
            transforms.swirl,
            seamless=Seamlessness.BREAKS,
        ),
        _definition(
            "transform.polar",
            "Polar Coordinates",
            "Spatial",
            "Reprojects the image around its center into angular/radial coordinates.",
            "scalar",
            (_p("radial_scale", "Radial Scale", F, 1.0, 0.1, 4.0, 0.05),),
            transforms.polar_coordinates,
            seamless=Seamlessness.BREAKS,
        ),
        _definition(
            "transform.kaleidoscope",
            "Kaleidoscope",
            "Spatial",
            "Folds the source into configurable radial symmetry wedges.",
            "scalar",
            (
                _p("segments", "Segments", INT, 8, 2, 32, 1, mod=False),
                rotation(),
                _p("radial_scale", "Radial Scale", F, 1.0, 0.1, 4.0, 0.05),
            ),
            transforms.kaleidoscope,
            seamless=Seamlessness.BREAKS,
        ),
        _definition(
            "transform.tile_scale_rotate",
            "Tile / Scale / Rotate",
            "Spatial",
            "Repeats a source while scaling and rotating its tiled coordinates.",
            "scalar",
            (_p("scale", "Tile Scale", F, 2.0, 0.1, 16.0, 0.05), rotation()),
            transforms.tile_transform,
            seamless=Seamlessness.UNKNOWN,
        ),
        _definition(
            "transform.pixelate",
            "Pixelate",
            "Detail",
            "Reduces spatial detail to configurable square pixel blocks.",
            "scalar",
            (_p("block_size", "Block Size", INT, 6, 1, 128, 1, mod=False),),
            transforms.pixelate,
            seamless=Seamlessness.UNKNOWN,
        ),
        _definition(
            "transform.edge_detect",
            "Edge Detect",
            "Detail",
            "Detects wrapped field boundaries with Sobel, Prewitt, or Laplacian kernels.",
            "scalar",
            (_p("method", "Method", E, "sobel", options=("sobel", "prewitt", "laplacian")),),
            transforms.edge_detect,
            seamless=Seamlessness.PRESERVES,
        ),
    ]
    return tuple(definitions)
