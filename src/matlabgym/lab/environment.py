"""Agent-facing Gym-style wrapper around :mod:`matlabgym.lab.runtime`."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Tuple

from ..api import canonical_action, make_info
from ..benchmark import (
    EndpointEvidence,
    EndpointName,
    EpisodeOutcome,
    FunnelSummary,
    TrialEndpoints,
    failure_category,
)
from ..core import Action, Observation, StepResult
from .contracts import (
    EnvironmentManifest,
    LabTaskSpec,
    OperationResult,
    RewardSpec,
    is_finite_number,
)
from .runtime import LabRuntime


class ConfigurableReward:
    """A versioned reward model supplied by the benchmark designer."""

    def __init__(self, spec: RewardSpec):
        self.spec = spec

    def __call__(
        self,
        results: Tuple[OperationResult, ...],
        elapsed_min: float,
        goal_reached: bool,
    ) -> float:
        return sum(self.components(results, elapsed_min, goal_reached).values())

    def components(
        self,
        results: Tuple[OperationResult, ...],
        elapsed_min: float,
        goal_reached: bool,
    ) -> Dict[str, float]:
        components = dict.fromkeys(("accepted", "completed", "invalid", "stopped", "cost"), 0.0)
        for result in results:
            if result.replayed:
                continue
            if not result.success:
                components["invalid"] += self.spec.invalid
            elif result.status == "accepted":
                components["accepted"] += self.spec.accepted
            elif result.status == "completed":
                components["completed"] += self.spec.completed
            elif result.status == "stopped":
                components["stopped"] += self.spec.stopped
            components["cost"] -= self.spec.cost_weight * result.incremental_cost
        components["time"] = -self.spec.time_weight * elapsed_min
        components["goal"] = self.spec.goal if goal_reached else 0.0
        return components


class LabGymEnv:
    """A deterministic environment with start/stop/advance/poll actions.

    ``reset`` follows the modern Gymnasium return shape ``(observation, info)``
    without requiring Gymnasium as a runtime dependency.  ``step`` keeps the
    project's existing :class:`StepResult` contract.
    """

    def __init__(
        self,
        runtime: LabRuntime,
        task: LabTaskSpec,
        manifest: EnvironmentManifest,
        reward_model: Optional[ConfigurableReward] = None,
    ) -> None:
        self.runtime = runtime
        self.task = task
        self.manifest = manifest
        self.reward_model = reward_model or ConfigurableReward(manifest.reward)
        self._assert_manifest_consistent()
        self._episode_counter = 0
        self.seed = 0
        self.episode_id = "uninitialized"
        self.step_count = 0
        self.terminated = False
        self.truncated = False
        self.last_outcome: Optional[Mapping[str, Any]] = None
        self._trace: List[Dict[str, Any]] = []

    def _assert_manifest_consistent(self) -> None:
        if self.task != self.manifest.task:
            raise ValueError("task does not match the environment manifest")
        if self.runtime.registry_hash != self.manifest.registry_hash:
            raise ValueError("runtime registry does not match the environment manifest")
        if self.runtime.platform_hash != self.manifest.platform_hash:
            raise ValueError("runtime platform does not match the environment manifest")
        if self.runtime.budget_money != self.task.budget_money:
            raise ValueError("runtime budget does not match the task")
        if self.runtime.backend != self.manifest.backend:
            raise ValueError("runtime backend does not match the environment manifest")
        if self.runtime.schema_version != self.manifest.schema_version:
            raise ValueError("runtime schema does not match the environment manifest")
        if type(self.reward_model) is not ConfigurableReward:
            raise ValueError("custom reward implementations require a versioned manifest contract")
        if self.reward_model.spec != self.manifest.reward:
            raise ValueError("reward model does not match the environment manifest")

    @property
    def reset_count(self):
        return self._episode_counter

    def _rejected(self, request_id: str, reason: str) -> OperationResult:
        return OperationResult(
            success=False,
            status="rejected",
            request_id=request_id,
            total_cost=self.runtime.total_cost,
            failure_code="INVALID_PARAMETER",
            failure_reason=reason,
        )

    @staticmethod
    def _trace_action(action: Action, parameters: Mapping[str, Any]) -> Dict[str, Any]:
        try:
            safe_parameters = json.loads(json.dumps(parameters, allow_nan=False))
        except (TypeError, ValueError):
            safe_parameters = {"_invalid_payload": True}
        return {"name": str(action.name), "parameters": safe_parameters}

    @staticmethod
    def _endpoint_evidence(results: Tuple[OperationResult, ...]) -> Tuple[EndpointEvidence, ...]:
        statuses = {result.status for result in results}
        artifacts = tuple(
            artifact_id for result in results for artifact_id in result.produced_artifact_ids
        )
        return (
            EndpointEvidence(
                EndpointName.PLAN_MATERIALIZED,
                bool({"accepted", "completed"} & statuses),
                "deterministic_compiler",
                artifacts,
            ),
            EndpointEvidence(
                EndpointName.DISPATCH_VERIFIED,
                bool({"accepted", "completed"} & statuses),
                "deterministic_resource_reservation",
                artifacts,
            ),
            EndpointEvidence(
                EndpointName.STARTED,
                False,
                "not_claimed_by_simulator",
                reason="logical running state is not physical start evidence",
            ),
            EndpointEvidence(
                EndpointName.COMPLETED,
                "completed" in statuses,
                "deterministic_completion",
                artifacts,
            ),
            EndpointEvidence(
                EndpointName.SCIENTIFICALLY_VALIDATED,
                False,
                "no_registered_scientific_oracle",
                reason="execution scaffold does not validate a scientific outcome",
            ),
        )

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Mapping[str, Any]] = None,
    ) -> Tuple[Observation, Mapping[str, Any]]:
        if options:
            raise ValueError("reset options are not supported")
        self._assert_manifest_consistent()
        self._episode_counter += 1
        self.seed = int(seed or 0)
        self.episode_id = "ep-%d-%04d" % (self.seed, self._episode_counter)
        self.step_count = 0
        self.terminated = False
        self.truncated = False
        self.last_outcome: Optional[Mapping[str, Any]] = None
        self._trace = []
        self.runtime.reset(self.episode_id, self.seed)
        observation = self.observe()
        info = make_info(
            episode_id=self.episode_id,
            manifest_hash=self.manifest.manifest_hash,
            public_state=self.public_snapshot(),
            backend=self.manifest.backend,
            seed=self.seed,
            reward_version=self.manifest.reward.version,
            workspace_policy="in_memory_episode_isolation",
        )
        return observation, info

    def _goal_reached(self) -> bool:
        return any(
            artifact.artifact_kind == self.task.goal_output_kind
            for artifact in self.runtime.artifacts.values()
        )

    @property
    def budget_spec(self):
        return {
            "max_steps": self.task.max_steps,
            "max_time_min": self.task.max_time_min,
            "budget_money": self.task.budget_money,
        }

    def public_snapshot(self):
        return copy.deepcopy(self.runtime.snapshot())

    def action_specs(self):
        operations = self.runtime.registry.operations()
        skills = self.runtime.registry.skills()

        def spec(name, properties, required=()):
            return {
                "name": name,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(required),
                    "additionalProperties": False,
                },
            }

        common = {"request_id": {"type": "string"}}
        actions = [
            spec(
                "start_operation",
                {
                    **common,
                    "operation_id": {
                        "type": "string",
                        "enum": [x.operation_id for x in operations],
                    },
                    "parameters": {"type": "object"},
                    "input_id": {"type": ["string", "null"]},
                },
                ("operation_id",),
            ),
            spec(
                "start_skill",
                {
                    **common,
                    "skill_id": {"type": "string", "enum": [x.skill_id for x in skills]},
                    "parameters_by_step": {"type": "object"},
                    "input_id": {"type": ["string", "null"]},
                },
                ("skill_id",),
            ),
            spec("stop_job", {**common, "job_id": {"type": "string", "minLength": 1}}, ("job_id",)),
            spec("advance_time", {**common, "minutes": {"type": "number", "minimum": 0}}),
            spec("poll", common),
        ]

        def parameter_schema(operation, defaults=None):
            defaults = defaults or {}
            properties = {}
            for name, parameter in operation.parameters.items():
                contract = {"type": parameter.kind}
                if parameter.minimum is not None:
                    contract["minimum"] = parameter.minimum
                if parameter.maximum is not None:
                    contract["maximum"] = parameter.maximum
                if parameter.choices:
                    contract["enum"] = list(parameter.choices)
                if parameter.unit:
                    contract["x-unit"] = parameter.unit
                if name in defaults:
                    contract["default"] = defaults[name]
                properties[name] = contract
            return {
                "type": "object",
                "properties": properties,
                "required": [
                    name
                    for name, p in operation.parameters.items()
                    if p.required and name not in defaults
                ],
                "additionalProperties": False,
            }

        operation_contracts = {}
        operation_conditions = []
        for operation in operations:
            schema = parameter_schema(operation)
            operation_contracts[operation.operation_id] = {
                **operation.to_dict(),
                "parameter_schema": schema,
                "input_contract": {
                    "required": operation.input_kind is not None,
                    "artifact_kind": operation.input_kind,
                    "artifact_state": operation.input_state,
                },
            }
            required = []
            properties = {"parameters": schema}
            if schema["required"]:
                required.append("parameters")
            if operation.input_kind is not None:
                required.append("input_id")
                properties["input_id"] = {"type": "string", "minLength": 1}
            operation_conditions.append(
                {
                    "if": {
                        "properties": {"operation_id": {"const": operation.operation_id}},
                        "required": ["operation_id"],
                    },
                    "then": {"properties": properties, "required": required},
                }
            )
        actions[0]["parameters"]["allOf"] = operation_conditions
        skill_contracts = {}
        skill_conditions = []
        for skill in skills:
            step_schemas = {
                step.step_id: parameter_schema(
                    self.runtime.registry.operation(step.operation_id), step.default_parameters
                )
                for step in skill.steps
            }
            required_steps = [name for name, schema in step_schemas.items() if schema["required"]]
            by_step = {
                "type": "object",
                "properties": step_schemas,
                "required": required_steps,
                "additionalProperties": False,
            }
            first = self.runtime.registry.operation(skill.steps[0].operation_id)
            skill_contracts[skill.skill_id] = {
                **skill.to_dict(),
                "parameters_by_step_schema": by_step,
                "input_contract": {
                    "required": first.input_kind is not None,
                    "artifact_kind": first.input_kind,
                    "artifact_state": first.input_state,
                },
            }
            required = ["parameters_by_step"] if required_steps else []
            properties = {"parameters_by_step": by_step}
            if first.input_kind is not None:
                required.append("input_id")
                properties["input_id"] = {"type": "string", "minLength": 1}
            skill_conditions.append(
                {
                    "if": {
                        "properties": {"skill_id": {"const": skill.skill_id}},
                        "required": ["skill_id"],
                    },
                    "then": {"properties": properties, "required": required},
                }
            )
        actions[1]["parameters"]["allOf"] = skill_conditions
        actions[0]["operations"] = [x.operation_id for x in operations]
        actions[0]["registry"] = operation_contracts
        actions[1]["skills"] = [x.skill_id for x in skills]
        actions[1]["registry"] = skill_contracts
        return tuple(copy.deepcopy(actions))

    def _available_actions(self):
        return self.action_specs()

    def observe(self) -> Observation:
        return Observation(
            step=self.step_count,
            budget_remaining=max(0, int(self.task.max_steps - self.step_count)),
            available_actions=self._available_actions(),
            public_state=copy.deepcopy(self.runtime.snapshot()),
            last_outcome=copy.deepcopy(self.last_outcome),
        )

    def step(self, action: Action) -> StepResult:
        if self.terminated or self.truncated:
            raise RuntimeError("episode is finished; call reset()")
        self._assert_manifest_consistent()
        action = canonical_action(action)
        before = self.runtime.snapshot()
        elapsed = 0.0
        results: Tuple[OperationResult, ...]
        if isinstance(action.parameters, Mapping):
            parameters = dict(action.parameters)
            malformed_parameters = None
        else:
            parameters = {}
            malformed_parameters = "action parameters must be an object"
        request_id = str(
            parameters.get("request_id")
            or "%s-action-%04d" % (self.episode_id, self.step_count + 1)
        )

        specs = {spec["name"]: spec for spec in self.action_specs()}
        if action.name == "__invalid_payload__":
            malformed_parameters = "non-JSON action payload"
        elif action.name in specs:
            allowed = specs[action.name]["parameters"]["properties"]
            unknown = sorted(set(parameters) - set(allowed))
            if unknown:
                malformed_parameters = "unknown command parameters: %s" % unknown

        if malformed_parameters:
            results = (self._rejected(request_id, malformed_parameters),)
        elif action.name == "start_operation":
            operation_parameters = parameters.get("parameters", {})
            if not isinstance(operation_parameters, Mapping):
                results = (self._rejected(request_id, "parameters must be an object"),)
            else:
                result = self.runtime.submit_operation(
                    operation_id=str(parameters.get("operation_id", "")),
                    parameters=operation_parameters,
                    input_id=parameters.get("input_id"),
                    request_id=request_id,
                )
                results = (result,)
        elif action.name == "start_skill":
            parameters_by_step = parameters.get("parameters_by_step", {})
            if not isinstance(parameters_by_step, Mapping):
                results = (self._rejected(request_id, "parameters_by_step must be an object"),)
            else:
                result = self.runtime.submit_skill(
                    skill_id=str(parameters.get("skill_id", "")),
                    parameters_by_step=parameters_by_step,
                    input_id=parameters.get("input_id"),
                    request_id=request_id,
                )
                results = (result,)
        elif action.name == "stop_job":
            job_id = parameters.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                results = (self._rejected(request_id, "job_id must be a non-empty string"),)
            else:
                results = (self.runtime.stop_job(job_id, request_id),)
        elif action.name == "advance_time":
            requested_minutes = parameters.get("minutes", 0.0)
            runtime_minutes = requested_minutes
            if is_finite_number(requested_minutes) and requested_minutes >= 0:
                remaining = max(0.0, self.task.max_time_min - self.runtime.clock_min)
                runtime_minutes = min(float(requested_minutes), remaining)
            before_clock = self.runtime.clock_min
            results = self.runtime.advance_time(runtime_minutes, request_id)
            elapsed = self.runtime.clock_min - before_clock
        elif action.name == "poll":
            results = (
                OperationResult(
                    success=True,
                    status="polled",
                    request_id=request_id,
                    total_cost=self.runtime.total_cost,
                ),
            )
        else:
            results = (
                OperationResult(
                    success=False,
                    status="rejected",
                    request_id=request_id,
                    total_cost=self.runtime.total_cost,
                    failure_code="INVALID_ACTION",
                    failure_reason="unknown environment action: %s" % action.name,
                ),
            )

        self.step_count += 1
        goal_reached = self._goal_reached()
        if goal_reached:
            self.terminated = True
        if (
            self.step_count >= self.task.max_steps
            or self.runtime.clock_min >= self.task.max_time_min
            or self.runtime.total_cost > self.task.budget_money
        ):
            self.truncated = not goal_reached

        reward_components = self.reward_model.components(results, elapsed, goal_reached)
        reward = sum(reward_components.values())
        endpoint_evidence = self._endpoint_evidence(results)
        failure_code = next(
            (result.failure_code for result in results if result.failure_code), None
        )
        self.last_outcome = {
            "results": [result.to_dict() for result in results],
            "goal_reached": goal_reached,
            "state_hash": self.runtime.state_hash,
            "endpoint_evidence": [item.to_dict() for item in endpoint_evidence],
            "failure_category": failure_category(failure_code),
        }
        after = self.runtime.snapshot()
        self._trace.append(
            {
                "index": len(self._trace),
                "episode_id": self.episode_id,
                "reset_count": self.reset_count,
                "manifest_hash": self.manifest.manifest_hash,
                "before": before,
                "action": self._trace_action(action, parameters),
                "after": after,
                "results": [result.to_dict() for result in results],
                "endpoint_evidence": [item.to_dict() for item in endpoint_evidence],
                "failure_category": failure_category(failure_code),
                "reward": reward,
                "reward_components": dict(reward_components),
                "terminated": self.terminated,
                "truncated": self.truncated,
            }
        )
        info = make_info(
            episode_id=self.episode_id,
            manifest_hash=self.manifest.manifest_hash,
            public_state=after,
            backend=self.manifest.backend,
            results=results,
            reward_components=reward_components,
            failure_code=failure_code,
            costs=[
                {
                    "quantity": self.runtime.total_cost - before["total_cost"],
                    "unit": "configured_cost_unit",
                    "source": "configured",
                },
                {"quantity": elapsed, "unit": "minute", "source": "configured"},
            ],
            total_cost=self.runtime.total_cost,
            logical_time_min=self.runtime.clock_min,
            reward_version=self.manifest.reward.version,
            endpoint_evidence=[item.to_dict() for item in endpoint_evidence],
            failure_category=failure_category(failure_code),
        )
        self._trace[-1]["results"] = copy.deepcopy(info["results"])
        self._trace[-1]["info"] = copy.deepcopy(info)
        return StepResult(self.observe(), reward, self.terminated, self.truncated, info)

    def trace(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._trace)

    def endpoint_funnel(self) -> Dict[str, Any]:
        if not self._trace:
            return FunnelSummary.from_trials([]).to_dict()
        merged = {}
        failure_category_value = None
        for event in self._trace:
            for item in event.get("endpoint_evidence", []):
                endpoint = item["endpoint"]
                previous = merged.get(endpoint)
                merged[endpoint] = {
                    "endpoint": endpoint,
                    "present": bool(item["present"]) or bool(previous and previous["present"]),
                    "evidence_source": item["evidence_source"],
                    "artifact_refs": list(
                        set((previous or {}).get("artifact_refs", []))
                        | set(item.get("artifact_refs") or [])
                    ),
                    "reason": item.get("reason"),
                }
            failure_category_value = event.get("failure_category") or failure_category_value
        trials = [
            TrialEndpoints(
                trial_id=self.episode_id,
                evidence=tuple(
                    EndpointEvidence(
                        EndpointName(item["endpoint"]),
                        bool(item["present"]),
                        str(item["evidence_source"]),
                        tuple(item.get("artifact_refs") or ()),
                        item.get("reason"),
                    )
                    for item in merged.values()
                ),
                failure_category=failure_category_value,
            )
        ]
        return FunnelSummary.from_trials(trials).to_dict()

    def evaluate(self):
        events = self.trace()
        snapshot = events[-1]["after"] if events else {}
        evidence = [item for event in events for item in event.get("endpoint_evidence", ())]
        present = {item["endpoint"] for item in evidence if item["present"]}
        success = any(
            item.get("artifact_kind") == self.task.goal_output_kind
            for item in snapshot.get("artifacts", {}).values()
        )
        return {
            "task_id": self.task.task_id,
            "seed": self.seed,
            "success": success,
            "steps": len(events),
            "total_reward": sum(e["reward"] for e in events),
            "logical_time_min": float(snapshot.get("clock_min", 0)),
            "total_cost": float(snapshot.get("total_cost", 0)),
            "logical_plan_materialized": "plan_materialized" in present,
            "logical_dispatch_verified": "dispatch_verified" in present,
            "logical_completed": "completed" in present,
            "scientifically_validated": False,
            "failure_categories": sorted(
                {e["failure_category"] for e in events if e.get("failure_category")}
            ),
            "artifact_refs": sorted(
                {ref for item in evidence for ref in item.get("artifact_refs", ())}
            ),
        }

    def episode_outcome(self):
        report = self.evaluate()
        return EpisodeOutcome(
            logical_plan_materialized=report["logical_plan_materialized"],
            logical_dispatch_verified=report["logical_dispatch_verified"],
            logical_completed=report["logical_completed"],
            physical_started=False,
            physical_completed=False,
            scientifically_validated=False,
            goal_reached=report["success"],
            failure_categories=tuple(report["failure_categories"]),
            total_reward=report["total_reward"],
            logical_time_min=report["logical_time_min"],
            total_cost=report["total_cost"],
            artifact_refs=tuple(report["artifact_refs"]),
        )
