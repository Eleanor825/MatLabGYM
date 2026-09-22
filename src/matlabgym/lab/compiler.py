"""Hardware-independent protocol to platform-bound execution plan compiler."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any, Dict, Optional

from .contracts import (
    CompiledProtocol,
    CompiledStep,
    ProtocolSpec,
    ProtocolStep,
    ResourceSpec,
    SkillSpec,
    stable_hash,
)
from .registry import SkillRegistry, platform_hash


class CompilationError(ValueError):
    pass


class ProtocolCompiler:
    """Bind abstract operations to concrete resources and validate the chain."""

    def __init__(self, registry: SkillRegistry, resources: Sequence[ResourceSpec]):
        self.registry = registry
        self.resources = tuple(resources)

    def _resource_for(
        self,
        resource_type: str,
        resource_loads: Mapping[str, int],
    ) -> ResourceSpec:
        matches = sorted(
            (resource for resource in self.resources if resource.resource_type == resource_type),
            key=lambda item: (
                resource_loads.get(item.resource_id, 0) >= item.capacity,
                resource_loads.get(item.resource_id, 0) / item.capacity,
                item.resource_id,
            ),
        )
        if not matches:
            raise CompilationError("no resource for type: %s" % resource_type)
        return matches[0]

    def compile(
        self,
        protocol: ProtocolSpec,
        artifact_types: Optional[Mapping[str, Mapping[str, str]]] = None,
        interruptible: bool = True,
        resource_loads: Optional[Mapping[str, int]] = None,
    ) -> CompiledProtocol:
        artifact_types = artifact_types or {}
        resource_loads = resource_loads or {}
        outputs: Dict[str, Dict[str, str]] = {}
        compiled = []
        total_duration = 0.0
        total_cost = 0.0
        seen = set()
        consumed_inputs = set()
        operations_interruptible = True

        for step in protocol.steps:
            if step.step_id in seen:
                raise CompilationError("duplicate step id: %s" % step.step_id)
            seen.add(step.step_id)
            try:
                operation = self.registry.operation(step.operation_id)
                operation.validate_parameters(step.parameters)
            except ValueError as exc:
                raise CompilationError("%s: %s" % (step.step_id, exc)) from exc

            input_descriptor = None
            if step.input_ref:
                if step.input_ref.startswith("step:"):
                    source = step.input_ref.split(":", 1)[1]
                    input_descriptor = outputs.get(source)
                    if input_descriptor is None:
                        raise CompilationError(
                            "%s references unavailable step: %s" % (step.step_id, source)
                        )
                elif step.input_ref.startswith("artifact:"):
                    source = step.input_ref.split(":", 1)[1]
                    input_descriptor = artifact_types.get(source)
                    if input_descriptor is None:
                        raise CompilationError(
                            "%s references unavailable artifact: %s" % (step.step_id, source)
                        )
                else:
                    raise CompilationError("invalid input_ref: %s" % step.input_ref)

            if operation.input_kind is None and input_descriptor is not None:
                raise CompilationError("%s does not accept an input artifact" % step.operation_id)
            if operation.input_kind is not None:
                if input_descriptor is None:
                    raise CompilationError("%s requires an input artifact" % step.operation_id)
                if input_descriptor["kind"] != operation.input_kind:
                    raise CompilationError(
                        "%s expects %s, got %s"
                        % (step.operation_id, operation.input_kind, input_descriptor["kind"])
                    )
                if operation.input_state and input_descriptor["state"] != operation.input_state:
                    raise CompilationError(
                        "%s expects state %s, got %s"
                        % (step.operation_id, operation.input_state, input_descriptor["state"])
                    )
            if operation.consumes_input and step.input_ref:
                if step.input_ref in consumed_inputs:
                    raise CompilationError(
                        "%s consumes an input already used in this protocol" % step.step_id
                    )
                consumed_inputs.add(step.input_ref)

            resource = self._resource_for(operation.resource_type, resource_loads)
            compiled.append(
                CompiledStep(
                    step_id=step.step_id,
                    operation_id=step.operation_id,
                    resource_id=resource.resource_id,
                    parameters=copy.deepcopy(dict(step.parameters)),
                    input_ref=step.input_ref,
                )
            )
            outputs[step.step_id] = {"kind": operation.output_kind, "state": operation.output_state}
            total_duration += operation.duration_min
            total_cost += operation.cost
            operations_interruptible = operations_interruptible and operation.interruptible

        if not compiled:
            raise CompilationError("protocol must contain at least one step")
        return CompiledProtocol(
            protocol_id=protocol.protocol_id,
            steps=tuple(compiled),
            registry_hash=self.registry.snapshot_hash,
            platform_hash=platform_hash(self.resources),
            source_hash=stable_hash(protocol.to_dict()),
            source_protocol=copy.deepcopy(protocol),
            total_duration_min=total_duration,
            total_cost=total_cost,
            interruptible=bool(interruptible) and operations_interruptible,
        )

    def compile_operation(
        self,
        operation_id: str,
        parameters: Mapping[str, Any],
        input_id: Optional[str],
        artifact_types: Mapping[str, Mapping[str, str]],
        resource_loads: Optional[Mapping[str, int]] = None,
    ) -> CompiledProtocol:
        input_ref = "artifact:%s" % input_id if input_id else None
        protocol = ProtocolSpec(
            protocol_id="operation:%s" % operation_id,
            steps=(ProtocolStep("operation", operation_id, dict(parameters), input_ref),),
        )
        return self.compile(
            protocol,
            artifact_types=artifact_types,
            interruptible=self.registry.operation(operation_id).interruptible,
            resource_loads=resource_loads,
        )

    def compile_skill(
        self,
        skill: SkillSpec,
        parameters_by_step: Mapping[str, Mapping[str, Any]],
        input_id: Optional[str],
        artifact_types: Mapping[str, Mapping[str, str]],
        resource_loads: Optional[Mapping[str, int]] = None,
    ) -> CompiledProtocol:
        known_steps = {step.step_id for step in skill.steps}
        unknown_steps = sorted(set(parameters_by_step) - known_steps)
        if unknown_steps:
            raise CompilationError("unknown skill step overrides: %s" % unknown_steps)
        steps = []
        previous = None
        for index, skill_step in enumerate(skill.steps):
            overrides = parameters_by_step.get(skill_step.step_id, {})
            if not isinstance(overrides, Mapping):
                raise CompilationError("parameters for %s must be an object" % skill_step.step_id)
            parameters = copy.deepcopy(dict(skill_step.default_parameters))
            parameters.update(copy.deepcopy(dict(overrides)))
            if index == 0:
                input_ref = "artifact:%s" % input_id if input_id else None
            else:
                input_ref = "step:%s" % previous
            steps.append(
                ProtocolStep(skill_step.step_id, skill_step.operation_id, parameters, input_ref)
            )
            previous = skill_step.step_id
        protocol = ProtocolSpec("skill:%s" % skill.skill_id, tuple(steps), version=skill.version)
        return self.compile(
            protocol,
            artifact_types=artifact_types,
            interruptible=skill.interruptible,
            resource_loads=resource_loads,
        )
