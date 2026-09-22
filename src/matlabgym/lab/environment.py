"""Agent-facing Gym-style wrapper around :mod:`matlabgym.lab.runtime`."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Tuple

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
        reward = 0.0
        for result in results:
            if result.replayed:
                continue
            if not result.success:
                reward += self.spec.invalid
            elif result.status == "accepted":
                reward += self.spec.accepted
            elif result.status == "completed":
                reward += self.spec.completed
            elif result.status == "stopped":
                reward += self.spec.stopped
            reward -= self.spec.cost_weight * result.incremental_cost
        reward -= self.spec.time_weight * elapsed_min
        if goal_reached:
            reward += self.spec.goal
        return reward


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

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Mapping[str, Any]] = None,
    ) -> Tuple[Observation, Mapping[str, Any]]:
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
        info = {
            "episode_id": self.episode_id,
            "seed": self.seed,
            "manifest_hash": self.manifest.manifest_hash,
            "reward_version": self.manifest.reward.version,
            "workspace_policy": "in_memory_episode_isolation",
        }
        return observation, info

    def _goal_reached(self) -> bool:
        return any(
            artifact.artifact_kind == self.task.goal_output_kind
            for artifact in self.runtime.artifacts.values()
        )

    def _available_actions(self):
        return (
            {
                "name": "start_operation",
                "operations": [item.operation_id for item in self.runtime.registry.operations()],
            },
            {
                "name": "start_skill",
                "skills": [item.skill_id for item in self.runtime.registry.skills()],
            },
            {"name": "stop_job"},
            {"name": "advance_time"},
            {"name": "poll"},
        )

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

        reward = self.reward_model(results, elapsed, goal_reached)
        self.last_outcome = {
            "results": [result.to_dict() for result in results],
            "goal_reached": goal_reached,
            "state_hash": self.runtime.state_hash,
        }
        after = self.runtime.snapshot()
        self._trace.append(
            {
                "index": len(self._trace),
                "episode_id": self.episode_id,
                "manifest_hash": self.manifest.manifest_hash,
                "before": before,
                "action": self._trace_action(action, parameters),
                "after": after,
                "results": [result.to_dict() for result in results],
                "reward": reward,
                "terminated": self.terminated,
                "truncated": self.truncated,
            }
        )
        info = {
            "episode_id": self.episode_id,
            "manifest_hash": self.manifest.manifest_hash,
            "state_hash": self.runtime.state_hash,
            "results": [result.to_dict() for result in results],
            "total_cost": self.runtime.total_cost,
            "logical_time_min": self.runtime.clock_min,
            "reward_version": self.manifest.reward.version,
        }
        return StepResult(self.observe(), reward, self.terminated, self.truncated, info)

    def trace(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._trace)
