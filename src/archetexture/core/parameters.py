from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ParameterType(str, Enum):
    FLOAT = "float"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUM = "enum"
    SEED = "seed"
    ANGLE = "angle"
    PERCENT = "percentage"
    COLOR = "color"
    POSITION_2D = "position_2d"


@dataclass(frozen=True)
class ParameterSpec:
    identifier: str
    name: str
    type: ParameterType
    default: Any = 0.0
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    description: str = ""
    animatable: bool = False
    allows_modulation: bool = True
    units: str | None = None
    options: tuple[str, ...] = ()
    required: bool = False


@dataclass(frozen=True)
class ControlFieldMapping:
    output_min: float = 0.0
    output_max: float = 1.0
    invert: bool = False
    curve: str = "linear"
    quantize: float | None = None

    def normalized_range(self) -> tuple[float, float]:
        return float(self.output_min), float(self.output_max)


@dataclass(frozen=True)
class ControlFieldBinding:
    source_id: str
    mapping: ControlFieldMapping = ControlFieldMapping()


ParameterValue = (
    float | int | bool | str | tuple[float, ...] | list[Any] | dict[str, Any] | ControlFieldBinding
)
