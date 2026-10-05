from __future__ import annotations

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.recipe import OperationInstance, ProjectRecipe


def default_recipe() -> ProjectRecipe:
    return ProjectRecipe(
        width=512,
        height=512,
        seed=31,
        source=OperationInstance(
            instance_id="source",
            operation_id="generator.white_noise",
            operation_version=1,
            parameters={"seed": 71},
        ),
        color_ramp=ColorRamp(
            (
                ColorStop(0.0, (0.025, 0.04, 0.11, 1.0)),
                ColorStop(0.48, (0.12, 0.42, 0.64, 1.0)),
                ColorStop(1.0, (0.96, 0.68, 0.27, 1.0)),
            )
        ),
    )
