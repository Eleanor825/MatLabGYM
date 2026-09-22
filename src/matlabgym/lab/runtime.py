"""Deterministic asynchronous runtime for simulated or adapted lab operations."""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

from .compiler import CompilationError, ProtocolCompiler
from .contracts import (
    Artifact,
    CompiledProtocol,
    FailureCode,
    Job,
    JobStatus,
    OperationResult,
    ResourceSpec,
    is_finite_number,
    stable_hash,
)
from .registry import RegistryError, SkillRegistry, platform_hash


class LabRuntime:
    """Execute compiled plans against an isolated logical lab state.

    Time is logical rather than wall-clock time.  This makes async execution,
    resource conflicts, ETA, stop behavior, and replay deterministic in tests.
    A real-lab adapter can implement the same result contract while mapping the
    clock and job states to an external scheduler.
    """

    backend = "deterministic-simulator"
    schema_version = "1.0"

    def __init__(
        self,
        registry: SkillRegistry,
        resources: Sequence[ResourceSpec],
        budget_money: float,
    ) -> None:
        if not is_finite_number(budget_money) or budget_money < 0:
            raise ValueError("budget_money must be a finite non-negative number")
        self.registry = registry
        self.resources = tuple(resources)
        resource_ids = [resource.resource_id for resource in self.resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("resource ids must be unique")
        self.registry.freeze()
        self.compiler = ProtocolCompiler(registry, resources)
        self.budget_money = float(budget_money)
        self.reset("uninitialized", seed=0)

    def reset(
        self,
        episode_id: str,
        seed: int,
        initial_artifacts: Iterable[Artifact] = (),
    ) -> None:
        self.episode_id = episode_id
        self.seed = seed
        self.clock_min = 0.0
        self.total_cost = 0.0
        self._job_counter = 0
        self._artifact_counter = 0
        self.jobs: Dict[str, Job] = {}
        self.artifacts: Dict[str, Artifact] = {}
        self.consumed_artifact_ids = set()
        self._artifact_allocations: Dict[str, str] = {}
        self._allocations: Dict[str, List[str]] = {
            resource.resource_id: [] for resource in self.resources
        }
        self._requests: Dict[str, Tuple[str, str]] = {}
        self._control_requests: Dict[str, Tuple[str, Tuple[OperationResult, ...]]] = {}
        self._events: List[Dict[str, Any]] = []
        for artifact in initial_artifacts:
            if artifact.episode_id != episode_id:
                raise ValueError("initial artifact belongs to another episode")
            if artifact.artifact_id in self.artifacts:
                raise ValueError("duplicate initial artifact id: %s" % artifact.artifact_id)
            self.artifacts[artifact.artifact_id] = copy.deepcopy(artifact)

    def artifact_types(self) -> Dict[str, Dict[str, str]]:
        return {
            artifact_id: {"kind": artifact.artifact_kind, "state": artifact.state}
            for artifact_id, artifact in self.artifacts.items()
        }

    def _new_job_id(self) -> str:
        self._job_counter += 1
        return "%s-job-%04d" % (self.episode_id, self._job_counter)

    def _new_artifact_id(self, kind: str) -> str:
        while True:
            self._artifact_counter += 1
            artifact_id = "%s-%s-%04d" % (
                self.episode_id,
                kind.replace("_", "-"),
                self._artifact_counter,
            )
            if artifact_id not in self.artifacts:
                return artifact_id

    def _failure(
        self,
        request_id: str,
        code: FailureCode,
        reason: str,
        retryable: bool = False,
    ) -> OperationResult:
        result = OperationResult(
            success=False,
            status="rejected",
            request_id=request_id,
            total_cost=self.total_cost,
            failure_code=code.value,
            failure_reason=reason,
            retryable=retryable,
        )
        self._record_event("rejected", result.to_dict())
        return result

    def _resource_map(self) -> Dict[str, ResourceSpec]:
        return {resource.resource_id: resource for resource in self.resources}

    def _resource_loads(self) -> Dict[str, int]:
        return {resource_id: len(job_ids) for resource_id, job_ids in self._allocations.items()}

    def _replay_or_conflict(
        self,
        request_id: str,
        request_hash: str,
    ) -> Optional[OperationResult]:
        prior = self._requests.get(request_id)
        if request_id in self._control_requests:
            return self._failure(
                request_id,
                FailureCode.REQUEST_CONFLICT,
                "request_id was already used for a control request",
            )
        if prior is None:
            return None
        prior_hash, prior_job_id = prior
        if prior_hash != request_hash:
            return self._failure(
                request_id,
                FailureCode.REQUEST_CONFLICT,
                "request_id was already used for a different request",
            )
        job = self.jobs[prior_job_id]
        return OperationResult(
            success=True,
            status=job.status.value,
            request_id=request_id,
            job_id=job.job_id,
            produced_artifact_ids=job.produced_artifact_ids,
            estimated_completion_min=job.estimated_completion_min,
            incremental_cost=0.0,
            total_cost=self.total_cost,
            replayed=True,
        )

    def _control_replay_or_conflict(
        self,
        request_id: str,
        request_hash: str,
    ) -> Optional[Tuple[OperationResult, ...]]:
        if request_id in self._requests:
            return (
                self._failure(
                    request_id,
                    FailureCode.REQUEST_CONFLICT,
                    "request_id was already used for a start request",
                ),
            )
        prior = self._control_requests.get(request_id)
        if prior is None:
            return None
        prior_hash, prior_results = prior
        if prior_hash != request_hash:
            return (
                self._failure(
                    request_id,
                    FailureCode.REQUEST_CONFLICT,
                    "request_id was already used for a different control request",
                ),
            )
        return tuple(
            replace(result, incremental_cost=0.0, replayed=True) for result in prior_results
        )

    def _remember_control(
        self,
        request_id: str,
        request_hash: str,
        results: Tuple[OperationResult, ...],
    ) -> Tuple[OperationResult, ...]:
        self._control_requests[request_id] = (request_hash, copy.deepcopy(results))
        return results

    def _validate_plan(self, plan: CompiledProtocol) -> Optional[str]:
        if plan.registry_hash != self.registry_hash:
            return "compiled plan registry hash does not match the runtime"
        if plan.platform_hash != self.platform_hash:
            return "compiled plan platform hash does not match the runtime"
        if plan.source_hash != stable_hash(plan.source_protocol.to_dict()):
            return "compiled plan source hash does not match its source protocol"
        if len(plan.steps) != len(plan.source_protocol.steps):
            return "compiled plan does not match its source protocol"

        resources = self._resource_map()
        outputs: Dict[str, Dict[str, str]] = {}
        seen = set()
        consumed_inputs = set()
        expected_duration = 0.0
        expected_cost = 0.0
        operations_interruptible = True
        for step, source_step in zip(plan.steps, plan.source_protocol.steps):
            if (
                step.step_id != source_step.step_id
                or step.operation_id != source_step.operation_id
                or step.input_ref != source_step.input_ref
                or stable_hash(step.parameters) != stable_hash(source_step.parameters)
            ):
                return "compiled step does not match its source protocol"
            if step.step_id in seen:
                return "compiled plan contains duplicate step id: %s" % step.step_id
            seen.add(step.step_id)
            try:
                operation = self.registry.operation(step.operation_id)
                operation.validate_parameters(step.parameters)
            except (RegistryError, ValueError) as exc:
                return str(exc)
            resource = resources.get(step.resource_id)
            if resource is None or resource.resource_type != operation.resource_type:
                return "resource %s cannot execute %s" % (step.resource_id, step.operation_id)

            descriptor = None
            if step.input_ref:
                if step.input_ref.startswith("step:"):
                    descriptor = outputs.get(step.input_ref.split(":", 1)[1])
                    if descriptor is None:
                        return "%s references an unavailable prior step" % step.step_id
                elif step.input_ref.startswith("artifact:"):
                    artifact = self.artifacts.get(step.input_ref.split(":", 1)[1])
                    if artifact is None:
                        return "%s references an unavailable artifact" % step.step_id
                    descriptor = {"kind": artifact.artifact_kind, "state": artifact.state}
                else:
                    return "invalid input_ref: %s" % step.input_ref

            if operation.input_kind is None and descriptor is not None:
                return "%s does not accept an input artifact" % operation.operation_id
            if operation.input_kind is not None:
                if descriptor is None:
                    return "%s requires an input artifact" % operation.operation_id
                if descriptor["kind"] != operation.input_kind:
                    return "%s input kind mismatch" % operation.operation_id
                if operation.input_state and descriptor["state"] != operation.input_state:
                    return "%s input state mismatch" % operation.operation_id
            if operation.consumes_input and step.input_ref:
                if step.input_ref in consumed_inputs:
                    return "%s consumes an input already used in this plan" % step.step_id
                consumed_inputs.add(step.input_ref)

            outputs[step.step_id] = {
                "kind": operation.output_kind,
                "state": operation.output_state,
            }
            expected_duration += operation.duration_min
            expected_cost += operation.cost
            operations_interruptible = operations_interruptible and operation.interruptible

        if not math.isclose(plan.total_duration_min, expected_duration, abs_tol=1e-12):
            return "compiled plan duration does not match registered operations"
        if not math.isclose(plan.total_cost, expected_cost, abs_tol=1e-12):
            return "compiled plan cost does not match registered operations"
        if plan.interruptible and not operations_interruptible:
            return "compiled plan weakens a non-interruptible operation"
        return None

    def _reserve(self, plan: CompiledProtocol, job_id: str) -> Optional[Tuple[FailureCode, str]]:
        resource_map = self._resource_map()
        requested = sorted(set(step.resource_id for step in plan.steps))
        external_inputs = sorted(
            step.input_ref.split(":", 1)[1]
            for step in plan.steps
            if step.input_ref and step.input_ref.startswith("artifact:")
        )
        for artifact_id in external_inputs:
            if artifact_id in self.consumed_artifact_ids:
                return (
                    FailureCode.ARTIFACT_CONSUMED,
                    "artifact was already consumed: %s" % artifact_id,
                )
            if artifact_id in self._artifact_allocations:
                return (
                    FailureCode.ARTIFACT_BUSY,
                    "artifact is allocated to another job: %s" % artifact_id,
                )
        for resource_id in requested:
            resource = resource_map[resource_id]
            if len(self._allocations[resource_id]) >= resource.capacity:
                return FailureCode.RESOURCE_BUSY, "resource is at capacity: %s" % resource_id
        for resource_id in requested:
            self._allocations[resource_id].append(job_id)
        for artifact_id in external_inputs:
            self._artifact_allocations[artifact_id] = job_id
        return None

    def _release(self, job: Job) -> None:
        for resource_id in sorted(set(step.resource_id for step in job.plan.steps)):
            if job.job_id in self._allocations[resource_id]:
                self._allocations[resource_id].remove(job.job_id)
        for artifact_id, allocated_job_id in list(self._artifact_allocations.items()):
            if allocated_job_id == job.job_id:
                del self._artifact_allocations[artifact_id]

    def submit_operation(
        self,
        operation_id: str,
        parameters: Mapping[str, Any],
        input_id: Optional[str],
        request_id: str,
    ) -> OperationResult:
        if not request_id:
            return self._failure(
                request_id, FailureCode.INVALID_PARAMETER, "request_id is required"
            )
        if not isinstance(parameters, Mapping):
            return self._failure(
                request_id, FailureCode.INVALID_PARAMETER, "parameters must be an object"
            )
        if input_id is not None and not isinstance(input_id, str):
            return self._failure(
                request_id, FailureCode.INVALID_PARAMETER, "input_id must be a string or null"
            )
        try:
            request_hash = stable_hash(
                {
                    "command": "start_operation",
                    "operation_id": operation_id,
                    "parameters": parameters,
                    "input_id": input_id,
                }
            )
        except (TypeError, ValueError) as exc:
            return self._failure(request_id, FailureCode.INVALID_PARAMETER, str(exc))
        replay = self._replay_or_conflict(request_id, request_hash)
        if replay is not None:
            return replay
        try:
            self.registry.operation(operation_id)
        except RegistryError as exc:
            return self._failure(request_id, FailureCode.UNKNOWN_OPERATION, str(exc))
        try:
            plan = self.compiler.compile_operation(
                operation_id,
                parameters,
                input_id,
                self.artifact_types(),
                resource_loads=self._resource_loads(),
            )
        except CompilationError as exc:
            return self._compilation_failure(request_id, str(exc))
        return self._submit_plan(plan, request_id, request_hash=request_hash)

    def submit_skill(
        self,
        skill_id: str,
        parameters_by_step: Mapping[str, Mapping[str, Any]],
        input_id: Optional[str],
        request_id: str,
    ) -> OperationResult:
        if not request_id:
            return self._failure(
                request_id, FailureCode.INVALID_PARAMETER, "request_id is required"
            )
        if not isinstance(parameters_by_step, Mapping):
            return self._failure(
                request_id,
                FailureCode.INVALID_PARAMETER,
                "parameters_by_step must be an object",
            )
        if input_id is not None and not isinstance(input_id, str):
            return self._failure(
                request_id, FailureCode.INVALID_PARAMETER, "input_id must be a string or null"
            )
        try:
            request_hash = stable_hash(
                {
                    "command": "start_skill",
                    "skill_id": skill_id,
                    "parameters_by_step": parameters_by_step,
                    "input_id": input_id,
                }
            )
        except (TypeError, ValueError) as exc:
            return self._failure(request_id, FailureCode.INVALID_PARAMETER, str(exc))
        replay = self._replay_or_conflict(request_id, request_hash)
        if replay is not None:
            return replay
        try:
            skill = self.registry.skill(skill_id)
            plan = self.compiler.compile_skill(
                skill,
                parameters_by_step,
                input_id,
                self.artifact_types(),
                resource_loads=self._resource_loads(),
            )
        except RegistryError as exc:
            return self._failure(request_id, FailureCode.UNKNOWN_SKILL, str(exc))
        except CompilationError as exc:
            return self._compilation_failure(request_id, str(exc))
        return self._submit_plan(plan, request_id, request_hash=request_hash)

    def _compilation_failure(self, request_id: str, reason: str) -> OperationResult:
        if "unavailable artifact" in reason or "requires an input" in reason:
            code = FailureCode.INPUT_NOT_FOUND
        elif "expects state" in reason:
            code = FailureCode.INPUT_STATE_MISMATCH
        elif "expects" in reason and "got" in reason:
            code = FailureCode.INPUT_KIND_MISMATCH
        else:
            code = FailureCode.INVALID_PARAMETER
        return self._failure(request_id, code, reason)

    def submit_plan(self, plan: CompiledProtocol, request_id: str) -> OperationResult:
        """Submit an externally compiled plan after full runtime validation."""
        return self._submit_plan(plan, request_id)

    def _submit_plan(
        self,
        plan: CompiledProtocol,
        request_id: str,
        request_hash: Optional[str] = None,
    ) -> OperationResult:
        if not request_id:
            return self._failure(
                request_id, FailureCode.INVALID_PARAMETER, "request_id is required"
            )
        if not isinstance(plan, CompiledProtocol):
            return self._failure(
                request_id, FailureCode.INVALID_PLAN, "plan must be a CompiledProtocol"
            )
        try:
            plan = copy.deepcopy(plan)
            plan_hash = stable_hash(plan.to_dict())
        except (AttributeError, TypeError, ValueError) as exc:
            return self._failure(request_id, FailureCode.INVALID_PLAN, str(exc))
        try:
            validation_error = self._validate_plan(plan)
        except (AttributeError, KeyError, OverflowError, TypeError, ValueError) as exc:
            return self._failure(request_id, FailureCode.INVALID_PLAN, str(exc))
        if validation_error:
            return self._failure(request_id, FailureCode.INVALID_PLAN, validation_error)
        request_hash = request_hash or plan_hash
        replay = self._replay_or_conflict(request_id, request_hash)
        if replay is not None:
            return replay
        if self.total_cost + plan.total_cost > self.budget_money:
            return self._failure(
                request_id,
                FailureCode.BUDGET_EXCEEDED,
                "plan cost %.2f exceeds remaining budget %.2f"
                % (plan.total_cost, self.budget_money - self.total_cost),
            )

        job_id = self._new_job_id()
        reservation_error = self._reserve(plan, job_id)
        if reservation_error:
            code, reason = reservation_error
            return self._failure(
                request_id,
                code,
                reason,
                retryable=code in {FailureCode.RESOURCE_BUSY, FailureCode.ARTIFACT_BUSY},
            )

        job = Job(
            job_id=job_id,
            request_id=request_id,
            plan=plan,
            episode_id=self.episode_id,
            start_time_min=self.clock_min,
            estimated_completion_min=self.clock_min + plan.total_duration_min,
        )
        self.jobs[job_id] = job
        self._requests[request_id] = (request_hash, job_id)
        self.total_cost += plan.total_cost
        result = OperationResult(
            success=True,
            status="accepted",
            request_id=request_id,
            job_id=job_id,
            estimated_completion_min=job.estimated_completion_min,
            incremental_cost=plan.total_cost,
            total_cost=self.total_cost,
        )
        self._record_event("accepted", {"result": result.to_dict(), "plan": plan.to_dict()})
        return result

    def advance_time(self, minutes: Any, request_id: str) -> Tuple[OperationResult, ...]:
        if not request_id:
            return (
                self._failure(request_id, FailureCode.INVALID_PARAMETER, "request_id is required"),
            )
        if not is_finite_number(minutes) or minutes < 0:
            return (
                self._failure(
                    request_id, FailureCode.INVALID_PARAMETER, "minutes must be non-negative"
                ),
            )
        request_hash = stable_hash({"command": "advance_time", "minutes": minutes})
        replay = self._control_replay_or_conflict(request_id, request_hash)
        if replay is not None:
            return replay
        self.clock_min += float(minutes)
        completed = []
        due = sorted(
            (
                job
                for job in self.jobs.values()
                if job.status == JobStatus.RUNNING
                and job.estimated_completion_min <= self.clock_min
            ),
            key=lambda item: (item.estimated_completion_min, item.job_id),
        )
        for job in due:
            completed.append(self._complete(job, request_id))
        if not completed:
            result = OperationResult(
                success=True,
                status="advanced",
                request_id=request_id,
                total_cost=self.total_cost,
            )
            self._record_event("advanced", {"minutes": minutes, "result": result.to_dict()})
            completed.append(result)
        return self._remember_control(request_id, request_hash, tuple(completed))

    def _complete(self, job: Job, request_id: str) -> OperationResult:
        outputs: Dict[str, str] = {}
        produced = []
        elapsed = 0.0
        for step in job.plan.steps:
            operation = self.registry.operation(step.operation_id)
            elapsed += operation.duration_min
            input_id = None
            if step.input_ref:
                if step.input_ref.startswith("artifact:"):
                    input_id = step.input_ref.split(":", 1)[1]
                else:
                    input_id = outputs[step.input_ref.split(":", 1)[1]]
            if input_id and operation.consumes_input:
                self.consumed_artifact_ids.add(input_id)
            artifact_id = self._new_artifact_id(operation.output_kind)
            artifact = Artifact(
                artifact_id=artifact_id,
                artifact_kind=operation.output_kind,
                state=operation.output_state,
                episode_id=self.episode_id,
                producer_job_id=job.job_id,
                parent_ids=(input_id,) if input_id else (),
                metadata={
                    "operation_id": operation.operation_id,
                    "parameters": copy.deepcopy(dict(step.parameters)),
                    "resource_id": step.resource_id,
                    "completed_at_min": job.start_time_min + elapsed,
                },
            )
            self.artifacts[artifact_id] = artifact
            outputs[step.step_id] = artifact_id
            produced.append(artifact_id)
        job.status = JobStatus.COMPLETED
        job.final_artifact_id = produced[-1]
        job.produced_artifact_ids = tuple(produced)
        self._release(job)
        result = OperationResult(
            success=True,
            status="completed",
            request_id=request_id,
            job_id=job.job_id,
            produced_artifact_ids=tuple(produced),
            estimated_completion_min=job.estimated_completion_min,
            total_cost=self.total_cost,
        )
        self._record_event("completed", result.to_dict())
        return result

    def stop_job(self, job_id: str, request_id: str) -> OperationResult:
        if not request_id:
            return self._failure(
                request_id, FailureCode.INVALID_PARAMETER, "request_id is required"
            )
        if not isinstance(job_id, str) or not job_id:
            return self._failure(
                request_id, FailureCode.INVALID_PARAMETER, "job_id must be a non-empty string"
            )
        request_hash = stable_hash({"command": "stop_job", "job_id": job_id})
        replay = self._control_replay_or_conflict(request_id, request_hash)
        if replay is not None:
            return replay[0]
        job = self.jobs.get(job_id)
        if job is None:
            result = self._failure(
                request_id, FailureCode.JOB_NOT_FOUND, "unknown job: %s" % job_id
            )
        elif job.status != JobStatus.RUNNING:
            result = self._failure(
                request_id,
                FailureCode.JOB_NOT_RUNNING,
                "job is not running: %s" % job.status.value,
            )
        elif not job.plan.interruptible:
            result = self._failure(
                request_id,
                FailureCode.NOT_INTERRUPTIBLE,
                "job contains a non-interruptible operation and cannot be stopped",
            )
        else:
            job.status = JobStatus.STOPPED
            self._release(job)
            result = OperationResult(
                success=True,
                status="stopped",
                request_id=request_id,
                job_id=job_id,
                total_cost=self.total_cost,
            )
            self._record_event("stopped", result.to_dict())
        self._remember_control(request_id, request_hash, (result,))
        return result

    def _record_event(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self._events.append(
            {
                "index": len(self._events),
                "episode_id": self.episode_id,
                "logical_time_min": self.clock_min,
                "event_type": event_type,
                "payload": copy.deepcopy(dict(payload)),
            }
        )

    def snapshot(self) -> Dict[str, Any]:
        resources = {
            resource.resource_id: {
                "resource_type": resource.resource_type,
                "capacity": resource.capacity,
                "allocated_jobs": list(self._allocations[resource.resource_id]),
            }
            for resource in self.resources
        }
        return {
            "episode_id": self.episode_id,
            "seed": self.seed,
            "clock_min": self.clock_min,
            "total_cost": self.total_cost,
            "budget_money": self.budget_money,
            "artifacts": {
                key: {
                    **value.to_dict(),
                    "available": key not in self.consumed_artifact_ids
                    and key not in self._artifact_allocations,
                    "allocated_job_id": self._artifact_allocations.get(key),
                }
                for key, value in sorted(self.artifacts.items())
            },
            "jobs": {key: value.to_dict() for key, value in sorted(self.jobs.items())},
            "resources": resources,
        }

    def events(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._events)

    @property
    def state_hash(self) -> str:
        return stable_hash(self.snapshot())

    @property
    def registry_hash(self) -> str:
        return self.registry.snapshot_hash

    @property
    def platform_hash(self) -> str:
        return platform_hash(self.resources)
