from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Mapping

if TYPE_CHECKING:
    import numpy as np

    Field = np.ndarray
else:
    Field = Any

OperationImplementation = Callable[[Field | None, Mapping[str, Any], int, int, int], Field]


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
    parameter_specs: tuple[Any, ...] = ()
    seamlessness: Seamlessness = Seamlessness.UNKNOWN
    implementation: OperationImplementation | None = field(default=None, compare=False, repr=False)


@dataclass
class OperationDefinitionSet:
    definitions: dict[str, OperationDefinition] = field(default_factory=dict)

    def register(
        self,
        definition: OperationDefinition,
        implementation: OperationImplementation | None = None,
        *,
        replace: bool = False,
    ) -> None:
        executor = implementation or definition.implementation
        if not callable(executor):
            raise ValueError(f"Operation {definition.identifier} has no implementation")
        if definition.identifier in self.definitions and not replace:
            raise ValueError(f"Operation already registered: {definition.identifier}")
        if definition.version < 1:
            raise ValueError("Operation versions must be positive")
        if not isinstance(definition.operation_type, OperationType):
            raise ValueError("Operation type must be declared")
        if definition.output_type not in {"scalar", "rgba"}:
            raise ValueError(f"Unsupported output field type: {definition.output_type}")
        if any(
            field_type not in {"scalar", "rgba", "any"} for field_type in definition.input_types
        ):
            raise ValueError("Operation input field types must be scalar, rgba, or any")
        identifiers = [spec.identifier for spec in definition.parameter_specs]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Operation parameter identifiers must be unique")
        self.definitions[definition.identifier] = OperationDefinition(
            identifier=definition.identifier,
            version=definition.version,
            name=definition.name,
            category=definition.category,
            description=definition.description,
            operation_type=definition.operation_type,
            input_types=definition.input_types,
            output_type=definition.output_type,
            parameter_specs=definition.parameter_specs,
            seamlessness=definition.seamlessness,
            implementation=executor,
        )

    def unregister(self, identifier: str) -> None:
        self.definitions.pop(identifier, None)

    def get(self, identifier: str) -> OperationDefinition:
        try:
            return self.definitions[identifier]
        except KeyError as exc:
            raise KeyError(f"Unknown operation identifier: {identifier}") from exc
