"""Operation and skill registry with immutable snapshot hashes."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from typing import Dict

from .contracts import OperationSpec, ResourceSpec, SkillSpec, stable_hash


class RegistryError(ValueError):
    pass


class SkillRegistry:
    def __init__(self) -> None:
        self._operations: Dict[str, OperationSpec] = {}
        self._skills: Dict[str, SkillSpec] = {}
        self._frozen = False

    def freeze(self) -> None:
        """Prevent capability changes after a benchmark manifest is created."""
        self._frozen = True

    def register_operation(self, spec: OperationSpec) -> None:
        if self._frozen:
            raise RegistryError("registry is frozen")
        if spec.operation_id in self._operations:
            raise RegistryError("duplicate operation: %s" % spec.operation_id)
        self._operations[spec.operation_id] = copy.deepcopy(spec)

    def register_skill(self, spec: SkillSpec) -> None:
        if self._frozen:
            raise RegistryError("registry is frozen")
        if spec.skill_id in self._skills:
            raise RegistryError("duplicate skill: %s" % spec.skill_id)
        if not spec.steps:
            raise RegistryError("skill must contain at least one step")
        missing = [
            step.operation_id for step in spec.steps if step.operation_id not in self._operations
        ]
        if missing:
            raise RegistryError("skill references unknown operations: %s" % sorted(set(missing)))
        if spec.interruptible and any(
            not self._operations[step.operation_id].interruptible for step in spec.steps
        ):
            raise RegistryError("interruptible skill contains a non-interruptible operation")
        self._skills[spec.skill_id] = copy.deepcopy(spec)

    def operation(self, operation_id: str) -> OperationSpec:
        try:
            return copy.deepcopy(self._operations[operation_id])
        except KeyError as exc:
            raise RegistryError("unknown operation: %s" % operation_id) from exc

    def skill(self, skill_id: str) -> SkillSpec:
        try:
            return copy.deepcopy(self._skills[skill_id])
        except KeyError as exc:
            raise RegistryError("unknown skill: %s" % skill_id) from exc

    def operations(self) -> Sequence[OperationSpec]:
        return tuple(copy.deepcopy(self._operations[key]) for key in sorted(self._operations))

    def skills(self) -> Sequence[SkillSpec]:
        return tuple(copy.deepcopy(self._skills[key]) for key in sorted(self._skills))

    def to_dict(self):
        return {
            "operations": [spec.to_dict() for spec in self.operations()],
            "skills": [spec.to_dict() for spec in self.skills()],
        }

    @property
    def snapshot_hash(self) -> str:
        return stable_hash(self.to_dict())


def platform_hash(resources: Iterable[ResourceSpec]) -> str:
    return stable_hash(
        [resource.to_dict() for resource in sorted(resources, key=lambda item: item.resource_id)]
    )
