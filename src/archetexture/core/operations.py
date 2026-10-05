from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from archetexture.core.parameters import ParameterSpec


class OperationType(str, Enum):
    GENERATOR = "generator"
    TRANSFORM = "transform"
    COLORIZER = "colorizer"


class Seamlessness(str, Enum):
    INHERENT = "inherent"
    WRAP_CAPABLE = "wrap_capable"
    PRESERVES = "preserves"
    BREAKS = "breaks"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OperationDefinition:
    identifier: str
    version: int
    name: str
    category: str
    description: str
    operation_type: OperationType
    input_types: tuple[str, ...]
    output_type: str
    parameter_specs: tuple[ParameterSpec, ...] = ()
    seamlessness: Seamlessness = Seamlessness.UNKNOWN


@dataclass
class OperationDefinitionSet:
    definitions: dict[str, OperationDefinition] = field(default_factory=dict)

    def register(self, definition: OperationDefinition) -> None:
        self.definitions[definition.identifier] = definition

    def get(self, identifier: str) -> OperationDefinition:
        try:
            return self.definitions[identifier]
        except KeyError as exc:
            raise KeyError(f"Unknown operation identifier: {identifier}") from exc
