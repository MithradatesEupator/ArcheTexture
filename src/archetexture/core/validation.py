from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationIssue:
    path: str
    message: str


class ValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        message = "; ".join(
            f"{issue.path}: {issue.message}" for issue in issues
        ) or "Validation failed"
        super().__init__(message)


def ensure_true(value: bool, path: str, message: str) -> None:
    if value is not True:
        raise ValidationError([ValidationIssue(path, message)])


def ensure_allowed(value: Any, *, allowed: tuple[Any, ...], path: str, message: str) -> None:
    if value not in allowed:
        raise ValidationError([ValidationIssue(path, message)])
