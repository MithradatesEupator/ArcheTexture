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
                "layer-noise",
                "Layer 1",
                OperationInstance(
                    "source-noise", "generator.white_noise", 1, parameters={"seed": 71}
                ),
                color_ramp=ColorRamp(
                    (
                        ColorStop(0.0, (0.0, 0.0, 0.0, 1.0)),
                        ColorStop(0.5, (0.5, 0.5, 0.5, 1.0)),
                        ColorStop(1.0, (1.0, 1.0, 1.0, 1.0)),
                    )
                ),
            ),
            LayerRecipe(
                "layer-gradient",
                "Layer 2",
                OperationInstance(
                    "source-gradient",
                    "generator.linear_gradient",
                    1,
                    parameters={"angle": 0.0},
                ),
                color_ramp=ColorRamp(
                    (
                        ColorStop(0.0, (0.18, 0.05, 0.28, 0.0)),
                        ColorStop(1.0, (0.94, 0.57, 0.18, 0.65)),
                    )
                ),
                opacity=0.3,
                blend_mode="screen",
            ),
        ],
    )
