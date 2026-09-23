"""Versioned contracts for protocol compilation and lab execution.

The module is intentionally dependency-free.  Every public value can be
serialized to JSON so episodes can be audited and replayed outside the agent
process.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

JsonDict = Dict[str, Any]


def stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % name)


def is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _require_finite(name: str, value: float, *, minimum: Optional[float] = None) -> None:
    if not is_finite_number(value):
        raise ValueError("%s must be a finite number" % name)
    if minimum is not None and value < minimum:
        raise ValueError("%s must be >= %s" % (name, minimum))


class JobStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class FailureCode(str, Enum):
    INVALID_ACTION = "INVALID_ACTION"
    UNKNOWN_OPERATION = "UNKNOWN_OPERATION"
    UNKNOWN_SKILL = "UNKNOWN_SKILL"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    INPUT_NOT_FOUND = "INPUT_NOT_FOUND"
    INPUT_KIND_MISMATCH = "INPUT_KIND_MISMATCH"
    INPUT_STATE_MISMATCH = "INPUT_STATE_MISMATCH"
    RESOURCE_BUSY = "RESOURCE_BUSY"
    ARTIFACT_BUSY = "ARTIFACT_BUSY"
    ARTIFACT_CONSUMED = "ARTIFACT_CONSUMED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_NOT_RUNNING = "JOB_NOT_RUNNING"
    NOT_INTERRUPTIBLE = "NOT_INTERRUPTIBLE"
    REQUEST_CONFLICT = "REQUEST_CONFLICT"
    INVALID_PLAN = "INVALID_PLAN"


@dataclass(frozen=True)
class ParameterSpec:
    kind: str
    required: bool = True
    unit: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"string", "number", "integer", "boolean", "object", "array"}:
            raise ValueError("unsupported parameter kind: %s" % self.kind)
        if not isinstance(self.required, bool):
            raise ValueError("required must be a boolean")
        if self.unit is not None and not isinstance(self.unit, str):
            raise ValueError("unit must be a string or null")
        if (self.minimum is not None or self.maximum is not None) and self.kind not in {
            "number",
            "integer",
        }:
            raise ValueError("minimum and maximum are only valid for numeric parameters")
        if self.minimum is not None:
            _require_finite("minimum", self.minimum)
        if self.maximum is not None:
            _require_finite("maximum", self.maximum)
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        if not isinstance(self.choices, tuple):
            raise ValueError("choices must be a tuple")
        for choice in self.choices:
            self.validate("choice", choice)

    def validate(self, name: str, value: Any) -> None:
        kinds = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "object": dict,
            "array": (list, tuple),
        }
        expected = kinds.get(self.kind)
        if expected is None:
            raise ValueError("unsupported parameter kind: %s" % self.kind)
        if self.kind in {"number", "integer"} and isinstance(value, bool):
            raise ValueError("%s must be %s" % (name, self.kind))
        if not isinstance(value, expected):
            raise ValueError("%s must be %s" % (name, self.kind))
        if self.kind in {"number", "integer"} and not is_finite_number(value):
            raise ValueError("%s must be finite" % name)
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("%s must contain only finite JSON-compatible values" % name) from exc
        if self.minimum is not None and value < self.minimum:
            raise ValueError("%s must be >= %s %s" % (name, self.minimum, self.unit or ""))
        if self.maximum is not None and value > self.maximum:
            raise ValueError("%s must be <= %s %s" % (name, self.maximum, self.unit or ""))
        if self.choices and value not in self.choices:
            raise ValueError("%s must be one of %s" % (name, list(self.choices)))

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ResourceSpec:
    resource_id: str
    resource_type: str
    capacity: int = 1
    version: str = "1.0"

    def __post_init__(self) -> None:
        _require_identifier("resource_id", self.resource_id)
        _require_identifier("resource_type", self.resource_type)
        _require_identifier("version", self.version)
        if (
            isinstance(self.capacity, bool)
            or not isinstance(self.capacity, int)
            or self.capacity <= 0
        ):
            raise ValueError("capacity must be a positive integer")

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    resource_type: str
    output_kind: str
    output_state: str
    parameters: Mapping[str, ParameterSpec] = field(default_factory=dict)
    input_kind: Optional[str] = None
    input_state: Optional[str] = None
    duration_min: float = 0.0
    cost: float = 0.0
    interruptible: bool = True
    consumes_input: bool = True
    version: str = "1.0"
    owner: str = "unassigned"
    provenance: str = ""

    def __post_init__(self) -> None:
        _require_identifier("operation_id", self.operation_id)
        _require_identifier("resource_type", self.resource_type)
        _require_identifier("output_kind", self.output_kind)
        _require_identifier("output_state", self.output_state)
        if not isinstance(self.parameters, Mapping) or not all(
            isinstance(name, str) and isinstance(spec, ParameterSpec)
            for name, spec in self.parameters.items()
        ):
            raise ValueError("parameters must map string names to ParameterSpec values")
        if self.input_kind is not None:
            _require_identifier("input_kind", self.input_kind)
        if self.input_state is not None:
            _require_identifier("input_state", self.input_state)
        if not isinstance(self.interruptible, bool):
            raise ValueError("interruptible must be a boolean")
        if not isinstance(self.consumes_input, bool):
            raise ValueError("consumes_input must be a boolean")
        _require_finite("duration_min", self.duration_min, minimum=0.0)
        _require_finite("cost", self.cost, minimum=0.0)

    def validate_parameters(self, values: Mapping[str, Any]) -> None:
        if not isinstance(values, Mapping):
            raise ValueError("parameters must be an object")
        unknown = sorted(set(values) - set(self.parameters))
        if unknown:
            raise ValueError("unknown parameters: %s" % unknown)
        for name, spec in self.parameters.items():
            if name not in values:
                if spec.required:
                    raise ValueError("missing required parameter: %s" % name)
                continue
            spec.validate(name, values[name])

    def to_dict(self) -> JsonDict:
        result = asdict(self)
        result["parameters"] = {name: spec.to_dict() for name, spec in self.parameters.items()}
        return result


@dataclass(frozen=True)
class SkillStep:
    step_id: str
    operation_id: str
    default_parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier("step_id", self.step_id)
        _require_identifier("operation_id", self.operation_id)
        if not isinstance(self.default_parameters, Mapping):
            raise ValueError("default_parameters must be an object")
        try:
            stable_hash(self.default_parameters)
        except (TypeError, ValueError) as exc:
            raise ValueError("default_parameters must be JSON-compatible") from exc

    def to_dict(self) -> JsonDict:
        return {
            "step_id": self.step_id,
            "operation_id": self.operation_id,
            "default_parameters": dict(self.default_parameters),
        }


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    steps: Tuple[SkillStep, ...]
    interruptible: bool = False
    version: str = "1.0"
    owner: str = "unassigned"

    def __post_init__(self) -> None:
        _require_identifier("skill_id", self.skill_id)
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ValueError("skill must contain at least one step")
        if not all(isinstance(step, SkillStep) for step in self.steps):
            raise ValueError("steps must contain SkillStep values")
        if not isinstance(self.interruptible, bool):
            raise ValueError("interruptible must be a boolean")
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("skill step ids must be unique")

    def to_dict(self) -> JsonDict:
        return {
            "skill_id": self.skill_id,
            "steps": [step.to_dict() for step in self.steps],
            "interruptible": self.interruptible,
            "version": self.version,
            "owner": self.owner,
        }


@dataclass(frozen=True)
class ProtocolStep:
    step_id: str
    operation_id: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    input_ref: Optional[str] = None

    def __post_init__(self) -> None:
        _require_identifier("step_id", self.step_id)
        _require_identifier("operation_id", self.operation_id)
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be an object")
        if self.input_ref is not None and not isinstance(self.input_ref, str):
            raise ValueError("input_ref must be a string or null")
        try:
            stable_hash(self.parameters)
        except (TypeError, ValueError) as exc:
            raise ValueError("parameters must be JSON-compatible") from exc

    def to_dict(self) -> JsonDict:
        return {
            "step_id": self.step_id,
            "operation_id": self.operation_id,
            "parameters": dict(self.parameters),
            "input_ref": self.input_ref,
        }


@dataclass(frozen=True)
class ProtocolSpec:
    protocol_id: str
    steps: Tuple[ProtocolStep, ...]
    version: str = "1.0"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier("protocol_id", self.protocol_id)
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ValueError("protocol must contain at least one step")
        if not all(isinstance(step, ProtocolStep) for step in self.steps):
            raise ValueError("steps must contain ProtocolStep values")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be an object")
        try:
            stable_hash(self.metadata)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-compatible") from exc

    def to_dict(self) -> JsonDict:
        return {
            "protocol_id": self.protocol_id,
            "steps": [step.to_dict() for step in self.steps],
            "version": self.version,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CompiledStep:
    step_id: str
    operation_id: str
    resource_id: str
    parameters: Mapping[str, Any]
    input_ref: Optional[str]

    def __post_init__(self) -> None:
        _require_identifier("step_id", self.step_id)
        _require_identifier("operation_id", self.operation_id)
        _require_identifier("resource_id", self.resource_id)
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be an object")
        if self.input_ref is not None and not isinstance(self.input_ref, str):
            raise ValueError("input_ref must be a string or null")
        try:
            stable_hash(self.parameters)
        except (TypeError, ValueError) as exc:
            raise ValueError("parameters must be JSON-compatible") from exc

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class CompiledProtocol:
    protocol_id: str
    steps: Tuple[CompiledStep, ...]
    registry_hash: str
    platform_hash: str
    source_hash: str
    source_protocol: ProtocolSpec
    total_duration_min: float
    total_cost: float
    interruptible: bool = True

    def __post_init__(self) -> None:
        _require_identifier("protocol_id", self.protocol_id)
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ValueError("compiled protocol must contain at least one step")
        if not all(isinstance(step, CompiledStep) for step in self.steps):
            raise ValueError("steps must contain CompiledStep values")
        for name in ("registry_hash", "platform_hash", "source_hash"):
            _require_identifier(name, getattr(self, name))
        if not isinstance(self.source_protocol, ProtocolSpec):
            raise ValueError("source_protocol must be a ProtocolSpec")
        if not isinstance(self.interruptible, bool):
            raise ValueError("interruptible must be a boolean")
        _require_finite("total_duration_min", self.total_duration_min, minimum=0.0)
        _require_finite("total_cost", self.total_cost, minimum=0.0)

    def to_dict(self) -> JsonDict:
        return {
            "protocol_id": self.protocol_id,
            "steps": [step.to_dict() for step in self.steps],
            "registry_hash": self.registry_hash,
            "platform_hash": self.platform_hash,
            "source_hash": self.source_hash,
            "source_protocol": self.source_protocol.to_dict(),
            "total_duration_min": self.total_duration_min,
            "total_cost": self.total_cost,
            "interruptible": self.interruptible,
        }


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    artifact_kind: str
    state: str
    episode_id: str
    producer_job_id: str
    parent_ids: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("artifact_id", "artifact_kind", "state", "episode_id", "producer_job_id"):
            _require_identifier(name, getattr(self, name))
        if not isinstance(self.parent_ids, tuple) or not all(
            isinstance(parent_id, str) for parent_id in self.parent_ids
        ):
            raise ValueError("parent_ids must be a tuple of strings")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be an object")

    def to_dict(self) -> JsonDict:
        return {
            "artifact_id": self.artifact_id,
            "artifact_kind": self.artifact_kind,
            "state": self.state,
            "episode_id": self.episode_id,
            "producer_job_id": self.producer_job_id,
            "parent_ids": list(self.parent_ids),
            "metadata": copy.deepcopy(dict(self.metadata)),
        }


@dataclass
class Job:
    job_id: str
    request_id: str
    plan: CompiledProtocol
    episode_id: str
    start_time_min: float
    estimated_completion_min: float
    status: JobStatus = JobStatus.RUNNING
    final_artifact_id: Optional[str] = None
    produced_artifact_ids: Tuple[str, ...] = ()
    failure_code: Optional[str] = None
    failure_reason: Optional[str] = None

    def to_dict(self) -> JsonDict:
        return {
            "job_id": self.job_id,
            "request_id": self.request_id,
            "protocol_id": self.plan.protocol_id,
            "episode_id": self.episode_id,
            "start_time_min": self.start_time_min,
            "estimated_completion_min": self.estimated_completion_min,
            "status": self.status.value,
            "final_artifact_id": self.final_artifact_id,
            "produced_artifact_ids": list(self.produced_artifact_ids),
            "failure_code": self.failure_code,
            "failure_reason": self.failure_reason,
            "interruptible": self.plan.interruptible,
        }


@dataclass(frozen=True)
class OperationResult:
    success: bool
    status: str
    request_id: str
    job_id: Optional[str] = None
    produced_artifact_ids: Tuple[str, ...] = ()
    estimated_completion_min: Optional[float] = None
    incremental_cost: float = 0.0
    total_cost: float = 0.0
    failure_code: Optional[str] = None
    failure_reason: Optional[str] = None
    retryable: bool = False
    replayed: bool = False
    endpoint: Optional[str] = None

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class LabTaskSpec:
    task_id: str
    goal_output_kind: str
    max_steps: int
    max_time_min: float
    budget_money: float
    version: str = "1.0"

    def __post_init__(self) -> None:
        _require_identifier("task_id", self.task_id)
        _require_identifier("goal_output_kind", self.goal_output_kind)
        if (
            isinstance(self.max_steps, bool)
            or not isinstance(self.max_steps, int)
            or self.max_steps <= 0
        ):
            raise ValueError("max_steps must be a positive integer")
        _require_finite("max_time_min", self.max_time_min, minimum=0.0)
        _require_finite("budget_money", self.budget_money, minimum=0.0)

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class RewardSpec:
    version: str = "1.0"
    accepted: float = 0.0
    completed: float = 0.1
    invalid: float = -1.0
    stopped: float = -0.2
    goal: float = 10.0
    cost_weight: float = 0.0
    time_weight: float = 0.0

    @classmethod
    def sparse_goal(cls, **overrides) -> "RewardSpec":
        values = {"version": "execution-sparse-v1", "completed": 0.0, "stopped": 0.0}
        values.update(overrides)
        return cls(**values)

    @classmethod
    def cost_aware(cls, **overrides) -> "RewardSpec":
        values = {
            "version": "execution-cost-aware-v1", "completed": 0.0, "stopped": 0.0,
            "cost_weight": 0.001, "time_weight": 0.0,
        }
        values.update(overrides)
        return cls(**values)

    def __post_init__(self) -> None:
        _require_identifier("version", self.version)
        for name in ("accepted", "completed", "invalid", "stopped", "goal"):
            _require_finite(name, getattr(self, name))
        _require_finite("cost_weight", self.cost_weight, minimum=0.0)
        _require_finite("time_weight", self.time_weight, minimum=0.0)

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class EnvironmentManifest:
    task: LabTaskSpec
    registry_hash: str
    platform_hash: str
    reward: RewardSpec
    backend: str = "deterministic-simulator"
    schema_version: str = "1.0"
    oracle_card_hash: str = "unregistered"
    evaluator_version: str = "execution-only-v1"
    success_predicate_hash: str = "execution-goal-v1"
    safety_policy_hash: str = "execution-safety-v1"
    split_hash: str = "unregistered"
    stress_suite_hash: str = "unregistered"

    def __post_init__(self) -> None:
        if not isinstance(self.task, LabTaskSpec):
            raise ValueError("task must be a LabTaskSpec")
        if not isinstance(self.reward, RewardSpec):
            raise ValueError("reward must be a RewardSpec")
        for name in (
            "registry_hash",
            "platform_hash",
            "backend",
            "schema_version",
            "oracle_card_hash",
            "evaluator_version",
            "success_predicate_hash",
            "safety_policy_hash",
            "split_hash",
            "stress_suite_hash",
        ):
            _require_identifier(name, getattr(self, name))

    def to_dict(self) -> JsonDict:
        return {
            "task": self.task.to_dict(),
            "registry_hash": self.registry_hash,
            "platform_hash": self.platform_hash,
            "reward": self.reward.to_dict(),
            "backend": self.backend,
            "schema_version": self.schema_version,
            "oracle_card_hash": self.oracle_card_hash,
            "evaluator_version": self.evaluator_version,
            "success_predicate_hash": self.success_predicate_hash,
            "safety_policy_hash": self.safety_policy_hash,
            "split_hash": self.split_hash,
            "stress_suite_hash": self.stress_suite_hash,
        }

    @property
    def manifest_hash(self) -> str:
        return stable_hash(self.to_dict())
