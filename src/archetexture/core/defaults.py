from __future__ import annotations

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.recipe import LayerRecipe, OperationInstance, ProjectRecipe


def default_recipe() -> ProjectRecipe:
    return ProjectRecipe(
        width=512,
        height=512,
        seed=31,
        layers=[
            LayerRecipe(
                "layer-fractal",
                "Layer 1",
                OperationInstance(
                    "source-fractal",
                    "generator.fractal_noise",
                    1,
                    parameters={
                        "seed": 23,
                        "scale": 3.5,
                        "octaves": 5,
                        "lacunarity": 2.0,
                        "persistence": 0.5,
                        "offset_x": 0.0,
                        "offset_y": 0.0,
                    },
                ),
                transforms=[
                    OperationInstance(
                        "fractal-levels",
                        "transform.levels",
                        1,
                        parameters={
                            "input_black": 0.12,
                            "input_white": 0.88,
                            "gamma": 0.9,
                            "output_black": 0.0,
                            "output_white": 1.0,
                        },
                    ),
                    OperationInstance(
                        "fractal-blur",
                        "transform.blur",
                        1,
                        parameters={"sigma": 0.6},
                    ),
                ],
                color_ramp=ColorRamp(
                    (
                        ColorStop(0.0, (0.025, 0.018, 0.012, 1.0)),
                        ColorStop(0.48, (0.24, 0.14, 0.075, 1.0)),
                        ColorStop(1.0, (0.84, 0.69, 0.43, 1.0)),
                    )
                ),
            ),
            LayerRecipe(
                "layer-cellular",
                "Layer 2",
                OperationInstance(
                    "source-cellular",
                    "generator.cellular",
                    1,
                    parameters={"seed": 61, "scale": 8.0, "jitter": 0.8, "distance_mode": "edge"},
                ),
                color_ramp=ColorRamp(
                    (
                        ColorStop(0.0, (0.10, 0.065, 0.035, 0.0)),
                        ColorStop(1.0, (0.95, 0.77, 0.48, 0.4)),
                    )
                ),
                opacity=0.3,
                blend_mode="screen",
            ),
        ],
    )
