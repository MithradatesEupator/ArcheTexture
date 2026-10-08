from __future__ import annotations

from dataclasses import dataclass, field

from archetexture.color.ramp import ColorRamp
from archetexture.core.outputs import semantic_definition
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
    mask: ControlFieldBinding | None = None


@dataclass
class MaterialOutputRecipe:
    output_id: str
    name: str
    semantic: str
    value_type: str
    layers: list[LayerRecipe] = field(default_factory=list)
    enabled: bool = True
    export_suffix: str | None = None
    clear_value: float | tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        definition = semantic_definition(self.semantic)
        if self.export_suffix is None:
            self.export_suffix = definition.export_suffix
        if self.clear_value is None:
            self.clear_value = definition.clear_value


@dataclass(init=False)
class ProjectRecipe:
    """Canonical schema-v5 material with a temporary first-output ``layers`` shim."""

    schema_version: int = 5
    width: int = 256
    height: int = 256
    seed: int = 0
    outputs: list[MaterialOutputRecipe] = field(default_factory=list)
    control_fields: dict[str, ControlFieldRecipe] = field(default_factory=dict)

    def __init__(
        self,
        schema_version: int = 5,
        width: int = 256,
        height: int = 256,
        seed: int = 0,
        layers: list[LayerRecipe] | None = None,
        control_fields: dict[str, ControlFieldRecipe] | None = None,
        *,
        source: OperationInstance | None = None,
        transforms: list[OperationInstance] | None = None,
        color_ramp: ColorRamp | None = None,
        outputs: list[MaterialOutputRecipe] | None = None,
    ) -> None:
        self.schema_version = schema_version
        self.width = width
        self.height = height
        self.seed = seed
        self.control_fields = {} if control_fields is None else control_fields
        if outputs is not None:
            self.outputs = outputs
        elif layers is not None:
            self.outputs = [
                MaterialOutputRecipe("output-1", "Texture", "custom_color", "color", layers)
            ]
        elif source is not None:
            self.outputs = [
                MaterialOutputRecipe(
                    "output-1",
                    "Texture",
                    "custom_color",
                    "color",
                    [
                        LayerRecipe(
                            "layer-1", "Layer 1", source, transforms or [], color_ramp=color_ramp
                        )
                    ],
                )
            ]
        else:
            self.outputs = []

    @property
    def layers(self) -> list[LayerRecipe]:
        """Compatibility shim for legacy callers; canonical data lives in outputs."""
        return self.outputs[0].layers if self.outputs else []

    @layers.setter
    def layers(self, value: list[LayerRecipe]) -> None:
        if self.outputs:
            self.outputs[0].layers = value
        else:
            self.outputs.append(
                MaterialOutputRecipe("output-1", "Texture", "custom_color", "color", value)
            )

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

    def output(self, output_id: str) -> MaterialOutputRecipe:
        for output in self.outputs:
            if output.output_id == output_id:
                return output
        raise KeyError(output_id)
