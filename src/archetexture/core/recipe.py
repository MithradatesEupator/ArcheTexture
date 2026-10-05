from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from archetexture.core.parameters import ControlFieldBinding, ParameterValue


@dataclass
class OperationInstance:
    instance_id: str
    operation_id: str
    operation_version: int
    enabled: bool = True
    parameters: dict[str, ParameterValue] = field(default_factory=dict)
    influence: float | ControlFieldBinding = 1.0


def _default_pipeline() -> list[OperationInstance]:
    return []


@dataclass
class ProjectRecipe:
    schema_version: int = 1
    width: int = 256
    height: int = 256
    seed: int = 0
    source: OperationInstance | None = None
    transforms: list[OperationInstance] = field(default_factory=_default_pipeline)
    color_ramp: Any | None = None


@dataclass
class ControlFieldRecipe:
    source: OperationInstance
    transforms: list[OperationInstance] = field(default_factory=list)
    mapping: Any | None = None

    def evaluate(self, width: int, height: int) -> Any:
        return None
