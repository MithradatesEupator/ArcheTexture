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
class LayerRecipe:
    layer_id: str
    name: str
    source: OperationInstance
    transforms: list[OperationInstance] = field(default_factory=list)
    color_ramp: ColorRamp | None = None
    enabled: bool = True
    opacity: float = 1.0
    blend_mode: str = "normal"


@dataclass(init=False)
class ProjectRecipe:
    """Canonical schema-v2 document, with temporary v1-shaped accessors for callers."""

    schema_version: int = 2
    width: int = 256
    height: int = 256
    seed: int = 0
    layers: list[LayerRecipe] = field(default_factory=list)
    control_fields: dict[str, ControlFieldRecipe] = field(default_factory=dict)

    def __init__(
        self,
        schema_version: int = 2,
        width: int = 256,
        height: int = 256,
        seed: int = 0,
        layers: list[LayerRecipe] | None = None,
        control_fields: dict[str, ControlFieldRecipe] | None = None,
        *,
        source: OperationInstance | None = None,
        transforms: list[OperationInstance] | None = None,
        color_ramp: ColorRamp | None = None,
    ) -> None:
        self.schema_version = schema_version
        self.width = width
        self.height = height
        self.seed = seed
        self.control_fields = {} if control_fields is None else control_fields
        if layers is not None:
            self.layers = layers
        elif source is not None:
            self.layers = [
                LayerRecipe("layer-1", "Layer 1", source, transforms or [], color_ramp=color_ramp)
            ]
        else:
            self.layers = []

    @property
    def source(self) -> OperationInstance | None:
        return self.layers[0].source if self.layers else None

    @source.setter
    def source(self, value: OperationInstance | None) -> None:
        if not self.layers:
            if value is None:
                return
            self.layers.append(LayerRecipe("layer-1", "Layer 1", value))
        elif value is not None:
            self.layers[0].source = value

    @property
    def transforms(self) -> list[OperationInstance]:
        return self.layers[0].transforms if self.layers else []

    @transforms.setter
    def transforms(self, value: list[OperationInstance]) -> None:
        if self.layers:
            self.layers[0].transforms = value

    @property
    def color_ramp(self) -> ColorRamp | None:
        return self.layers[0].color_ramp if self.layers else None

    @color_ramp.setter
    def color_ramp(self, value: ColorRamp | None) -> None:
        if self.layers:
            self.layers[0].color_ramp = value
