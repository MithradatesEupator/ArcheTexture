from __future__ import annotations

from dataclasses import dataclass, field

from archetexture.color.ramp import ColorRamp
from archetexture.core.parameters import (
    ControlFieldBinding,
    ControlFieldMapping,
    ParameterValue,
)


@dataclass
class OperationInstance:
    instance_id: str
    operation_id: str
    operation_version: int
    enabled: bool = True
    parameters: dict[str, ParameterValue] = field(default_factory=dict)
    influence: float | ControlFieldBinding = 1.0


@dataclass
class ControlFieldRecipe:
    source: OperationInstance
    transforms: list[OperationInstance] = field(default_factory=list)
    mapping: ControlFieldMapping | None = None


@dataclass
class ProjectRecipe:
    schema_version: int = 1
    width: int = 256
    height: int = 256
    seed: int = 0
    source: OperationInstance | None = None
    transforms: list[OperationInstance] = field(default_factory=list)
    color_ramp: ColorRamp | None = None
    control_fields: dict[str, ControlFieldRecipe] = field(default_factory=dict)
