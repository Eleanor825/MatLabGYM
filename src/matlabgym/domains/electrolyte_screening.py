"""A finite-support electrolyte screening campaign on the shared lab runtime.

Mixing must finish before characterization can start. Only a completed
characterization releases a frozen oracle measurement into the public state.
Timing, capacities and interruptibility are configurable simulation contracts,
not claims about a connected physical production line.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, replace
from typing import Mapping, Optional

from ..api import canonical_action, make_info
from ..benchmark import EpisodeOutcome, stable_hash
from ..core import Action, Observation, StepResult, TaskSpec
from ..electrolyte import ElectrolyteReplayEnv, OutcomeOracle
from ..lab import (
    EnvironmentManifest,
    LabGymEnv,
    LabRuntime,
    LabTaskSpec,
    OperationResult,
    OperationSpec,
    ParameterSpec,
    ResourceSpec,
    RewardSpec,
    SkillRegistry,
    SkillSpec,
    SkillStep,
)
from ..lab.contracts import JobStatus, is_finite_number
from ..lab.registry import platform_hash
from ..rewards import ReplayRewardSpec


@dataclass(frozen=True)
class ElectrolyteTask:
    task_id: str = "electrolyte.screening.v1"
    max_steps: int = 80
    max_measurements: int = 5
    target_conductivity: float = 12.0
    temperature_c: int = 30
    max_time_min: float = 2000.0
    mix_duration_min: float = 30.0
    characterization_duration_min: float = 45.0
    mixing_capacity: int = 1
    characterization_capacity: int = 1

    def __post_init__(self):
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be non-empty")
        for name in (
            "max_steps",
            "max_measurements",
            "mixing_capacity",
            "characterization_capacity",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("%s must be a positive integer" % name)
        for name in ("max_time_min", "mix_duration_min", "characterization_duration_min"):
            if not is_finite_number(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError("%s must be positive and finite" % name)
        if not is_finite_number(self.target_conductivity):
            raise ValueError("target_conductivity must be finite")
        if isinstance(self.temperature_c, bool) or not isinstance(self.temperature_c, int):
            raise ValueError("temperature_c must be an integer")

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ScreeningManifest:
    task: ElectrolyteTask
    reward: ReplayRewardSpec
    oracle_snapshot_hash: str
    registry_hash: str
    platform_hash: str
    backend: str
    schema_version: str = "1.0"
    evaluator_version: str = "supported-conductivity-v1"

    def to_dict(self):
        return asdict(self)

    @property
    def manifest_hash(self):
        return stable_hash(self.to_dict())


class ElectrolyteEnv:
    """Uniform asynchronous mix -> characterize -> decide environment."""

    def __init__(
        self,
        task: ElectrolyteTask,
        oracle: OutcomeOracle,
        *,
        reward: Optional[ReplayRewardSpec] = None,
    ):
        self.task = task
        self.reward_spec = reward or ReplayRewardSpec.cost_aware(
            scale=abs(task.target_conductivity) or 1.0
        )
        # Reuse the replay loader's deterministic snapshot/finite-value checks.
        replay = ElectrolyteReplayEnv(
            TaskSpec(
                task.task_id,
                "Screen supported electrolyte formulations",
                task.max_steps,
                task.max_measurements,
                task.target_conductivity,
            ),
            oracle,
            temperature_c=task.temperature_c,
            reward=self.reward_spec,
        )
        self._outcomes = copy.deepcopy(replay._outcomes)
        if not is_finite_number(
            self.reward_spec.measurement_cost * min(task.max_measurements, len(self._outcomes))
        ):
            raise ValueError("measurement reward cost overflows the campaign budget")
        supported_ids = {key[0] for key in self._outcomes}
        self._candidates = tuple(
            f.to_dict() for f in replay._candidates if f.formulation_id in supported_ids
        )
        registry = SkillRegistry()
        registry.register_operation(
            OperationSpec(
                "mix_electrolyte",
                "mixing_station",
                "electrolyte_batch",
                "mixed",
                parameters={
                    "formulation_id": ParameterSpec("string", choices=tuple(sorted(supported_ids))),
                    "batch_size_ml": ParameterSpec("number", unit="mL", minimum=1, maximum=1000),
                },
                duration_min=task.mix_duration_min,
                interruptible=True,
                owner="sandbox-owner",
                provenance="supported formulation catalog; simulated mixing",
            )
        )
        registry.register_operation(
            OperationSpec(
                "characterize_electrolyte",
                "conductivity_station",
                "conductivity_report",
                "measured",
                parameters={
                    "temperature_c": ParameterSpec(
                        "integer", unit="degC", choices=(task.temperature_c,)
                    )
                },
                input_kind="electrolyte_batch",
                input_state="mixed",
                duration_min=task.characterization_duration_min,
                interruptible=True,
                owner="sandbox-owner",
                provenance="frozen conductivity replay; simulated timing",
            )
        )
        registry.register_skill(
            SkillSpec(
                "measure_electrolyte",
                (
                    SkillStep("mix", "mix_electrolyte"),
                    SkillStep(
                        "characterize",
                        "characterize_electrolyte",
                        {"temperature_c": task.temperature_c},
                    ),
                ),
                interruptible=False,
                owner="sandbox-owner",
            )
        )
        resources = (
            ResourceSpec("mixer-01", "mixing_station", capacity=task.mixing_capacity),
            ResourceSpec(
                "conductivity-01", "conductivity_station", capacity=task.characterization_capacity
            ),
        )
        self.runtime = LabRuntime(registry, resources, budget_money=0.0)
        # LabGymEnv supplies the common command/registry JSON schemas only.
        lab_task = LabTaskSpec(
            task.task_id, "conductivity_report", task.max_steps, task.max_time_min, 0.0
        )
        lab_manifest = EnvironmentManifest(
            lab_task, registry.snapshot_hash, platform_hash(resources), RewardSpec.sparse_goal()
        )
        self._schema_env = LabGymEnv(self.runtime, lab_task, lab_manifest)
        self.manifest = ScreeningManifest(
            task,
            self.reward_spec,
            replay.manifest.oracle_snapshot_hash,
            registry.snapshot_hash,
            platform_hash(resources),
            "electrolyte-screening/" + replay.manifest.backend,
        )
        self.reset_count = 0
        self.reset(seed=0)

    @property
    def budget_spec(self):
        return {
            "max_steps": self.task.max_steps,
            "max_measurements": self.task.max_measurements,
            "max_time_min": self.task.max_time_min,
        }

    def _check_manifest(self):
        if (
            self.task != self.manifest.task
            or self.reward_spec != self.manifest.reward
            or self.runtime.registry_hash != self.manifest.registry_hash
            or self.runtime.platform_hash != self.manifest.platform_hash
        ):
            raise ValueError("configuration differs from frozen manifest")
        if (
            self.runtime.backend != "deterministic-simulator"
            or self.runtime.schema_version != "1.0"
            or self.runtime.budget_money != 0.0
        ):
            raise ValueError("runtime differs from frozen simulation contract")

    def reset(self, *, seed=None, options=None):
        if options:
            raise ValueError("construct a new environment to change configuration")
        self._check_manifest()
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise ValueError("seed must be an integer")
        self.seed = 0 if seed is None else seed
        self.reset_count += 1
        self.episode_id = "electrolyte-%d-%04d" % (self.seed, self.reset_count)
        self.runtime.reset(self.episode_id, self.seed)
        self.step_count = 0
        self.terminated = self.truncated = False
        self._measured = {}
        self._measurement_actions = []
        self._job_keys = {}
        self._requests = {}
        self._trace = []
        self.last_outcome = None
        return self.observe(), self._info(seed=self.seed)

    def action_specs(self):
        return self._schema_env.action_specs()

    def _pending(self):
        return {
            key
            for job_id, key in self._job_keys.items()
            if self.runtime.jobs[job_id].status == JobStatus.RUNNING
        }

    def public_snapshot(self):
        snapshot = self.runtime.snapshot()
        snapshot.update(
            {
                "task_id": self.task.task_id,
                "target_conductivity_ms_cm": self.task.target_conductivity,
                "candidates": copy.deepcopy(list(self._candidates)),
                "support_mask": [list(k) for k in sorted(self._outcomes)],
                "measurements": [m.to_dict() for m in self._measured.values()],
                "best_so_far_ms_cm": self._best(),
                "budgets": {
                    "actions_remaining": max(0, self.task.max_steps - self.step_count),
                    "measurements_remaining": self.task.max_measurements - len(self._measured),
                    "measurements_reserved": len(self._pending()),
                    "logical_minutes_remaining": max(
                        0, self.task.max_time_min - self.runtime.clock_min
                    ),
                },
                "step": self.step_count,
                "terminated": self.terminated,
                "truncated": self.truncated,
            }
        )
        # Runtime costs are intentionally disabled; a query cost is not money.
        snapshot.pop("total_cost", None)
        snapshot.pop("budget_money", None)
        return snapshot

    def observe(self):
        return Observation(
            self.step_count,
            self.task.max_measurements - len(self._measured),
            self.action_specs(),
            self.public_snapshot(),
            copy.deepcopy(self.last_outcome),
        )

    def _best(self):
        return max((m.conductivity_ms_cm for m in self._measured.values()), default=None)

    def _success(self):
        return self._best() is not None and self._best() >= self.task.target_conductivity

    def _info(self, results=(), components=None, query_cost=0, elapsed=0, **extra):
        failure = next((r.failure_code for r in results if r.failure_code), None)
        return make_info(
            episode_id=self.episode_id,
            manifest_hash=self.manifest.manifest_hash,
            public_state=self.public_snapshot(),
            backend=self.manifest.backend,
            results=results,
            reward_components=components,
            failure_code=failure,
            costs=[
                {"quantity": query_cost, "unit": "measurement_query", "source": "proxy"},
                {"quantity": elapsed, "unit": "minute", "source": "configured"},
            ],
            endpoint_evidence=[e.to_dict() for e in LabGymEnv._endpoint_evidence(tuple(results))],
            failure_category="invalid_action" if failure else None,
            success=self._success(),
            reward_version=self.reward_spec.version,
            logical_time_min=self.runtime.clock_min,
            total_query_cost=len(self._measured),
            calibration_status="unvalidated",
            **extra,
        )

    @staticmethod
    def _reject(request_id, code, reason):
        return OperationResult(
            False, "rejected", request_id, failure_code=code, failure_reason=reason
        )

    def _candidate_key(self, action, p):
        if action.name == "start_skill":
            if p.get("skill_id") != "measure_electrolyte":
                return None
            overrides = p.get("parameters_by_step", {})
            mix = overrides.get("mix", {})
            characterize = overrides.get("characterize", {})
            return (
                mix.get("formulation_id"),
                characterize.get("temperature_c", self.task.temperature_c),
            )
        if p.get("operation_id") == "characterize_electrolyte":
            artifact = self.runtime.artifacts.get(p.get("input_id"))
            if artifact is None:
                return None  # Runtime produces the precise input error.
            return (
                artifact.metadata.get("parameters", {}).get("formulation_id"),
                p.get("parameters", {}).get("temperature_c"),
            )
        return None

    def _execute(self, action, p, request_id):
        allowed = {
            "start_operation": {"request_id", "operation_id", "parameters", "input_id"},
            "start_skill": {"request_id", "skill_id", "parameters_by_step", "input_id"},
            "advance_time": {"request_id", "minutes"},
            "stop_job": {"request_id", "job_id"},
            "poll": {"request_id"},
        }
        if action.name == "__invalid_payload__":
            return (self._reject(request_id, "INVALID_PARAMETER", "non-JSON action payload"),)
        if action.name in allowed and set(p) - allowed[action.name]:
            return (self._reject(request_id, "INVALID_PARAMETER", "unknown command parameters"),)
        if action.name in {"start_operation", "start_skill"}:
            key = self._candidate_key(action, p)
            if key is not None:
                if key not in self._outcomes:
                    return (self._reject(request_id, "OUTSIDE_SUPPORT", "no observed outcome"),)
                if key in self._measured or key in self._pending():
                    return (
                        self._reject(
                            request_id,
                            "MEASUREMENT_ALREADY_REQUESTED",
                            "candidate already measured or reserved",
                        ),
                    )
                if len(self._measured) + len(self._pending()) >= self.task.max_measurements:
                    return (
                        self._reject(
                            request_id,
                            "BUDGET_EXCEEDED",
                            "measurement budget exhausted or reserved",
                        ),
                    )
            if action.name == "start_operation":
                result = self.runtime.submit_operation(
                    str(p.get("operation_id", "")),
                    p.get("parameters", {}),
                    p.get("input_id"),
                    request_id,
                )
            else:
                result = self.runtime.submit_skill(
                    str(p.get("skill_id", "")),
                    p.get("parameters_by_step", {}),
                    p.get("input_id"),
                    request_id,
                )
            if result.success and key is not None:
                self._job_keys[result.job_id] = key
            return (result,)
        if action.name == "advance_time":
            minutes = p.get("minutes", 0)
            if is_finite_number(minutes) and minutes >= 0:
                minutes = min(minutes, max(0, self.task.max_time_min - self.runtime.clock_min))
            return self.runtime.advance_time(minutes, request_id)
        if action.name == "stop_job":
            result = self.runtime.stop_job(p.get("job_id"), request_id)
            if result.success and result.status == "stopped":
                # A stopped characterization does not prove that the sample is reusable.
                job = self.runtime.jobs[result.job_id]
                for step in job.plan.steps:
                    if step.input_ref and step.input_ref.startswith("artifact:"):
                        aid = step.input_ref.split(":", 1)[1]
                        self.runtime.artifacts[aid] = replace(
                            self.runtime.artifacts[aid], state="quarantined"
                        )
            return (result,)
        if action.name == "poll":
            return (OperationResult(True, "polled", request_id),)
        return (self._reject(request_id, "INVALID_ACTION", "unknown command"),)

    def step(self, action: Action):
        if self.terminated or self.truncated:
            raise RuntimeError("episode is finished; call reset()")
        self._check_manifest()
        action = canonical_action(action)
        before = self.public_snapshot()
        best_before = self._best()
        clock_before = self.runtime.clock_min
        request_id = "%s-action-%d" % (self.episode_id, self.step_count + 1)
        replayed = False
        request_hash = None
        try:
            if not isinstance(action, Action) or not isinstance(action.parameters, Mapping):
                raise ValueError("action must have mapping parameters")
            p = copy.deepcopy(dict(action.parameters))
            supplied_id = p.get("request_id", request_id)
            if not isinstance(supplied_id, str) or not supplied_id.strip():
                raise ValueError("request_id must be a non-empty string")
            request_id = supplied_id
            request_hash = stable_hash(action.to_dict())
            previous = self._requests.get(request_id)
            if previous:
                if previous[0] != request_hash:
                    results = (
                        self._reject(
                            request_id,
                            "REQUEST_CONFLICT",
                            "request_id was used for a different action",
                        ),
                    )
                else:
                    results = tuple(
                        replace(r, replayed=True, incremental_cost=0.0) for r in previous[1]
                    )
                    replayed = True
            else:
                results = self._execute(action, p, request_id)
                if action.name != "poll" and all(r.success for r in results):
                    self._requests[request_id] = (request_hash, copy.deepcopy(results))
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError) as exc:
            results = (self._reject(request_id, "INVALID_PARAMETER", str(exc)),)

        new_measurements = []
        if not replayed:
            for result in results:
                if result.status != "completed":
                    continue
                for aid in result.produced_artifact_ids:
                    artifact = self.runtime.artifacts[aid]
                    if artifact.artifact_kind != "conductivity_report":
                        continue
                    key = self._job_keys[result.job_id]
                    if key in self._measured:
                        continue
                    measurement = self._outcomes[key]
                    self._measured[key] = measurement
                    self._measurement_actions.append(self.step_count + 1)
                    metadata = dict(artifact.metadata)
                    metadata.update(
                        {
                            "measurement": measurement.to_dict(),
                            "oracle_snapshot_hash": self.manifest.oracle_snapshot_hash,
                            "calibration_status": "unvalidated",
                        }
                    )
                    self.runtime.artifacts[aid] = replace(artifact, metadata=metadata)
                    new_measurements.append(measurement.to_dict())

        self.step_count += 1
        success = self._success()
        self.terminated = success or len(self._measured) == len(self._outcomes)
        self.truncated = not self.terminated and (
            len(self._measured) >= self.task.max_measurements
            or self.step_count >= self.task.max_steps
            or self.runtime.clock_min >= self.task.max_time_min
        )
        components = self.reward_spec.components(
            valid=all(r.success for r in results),
            previous_best=best_before,
            current_best=self._best(),
            goal_reached=success,
        )
        # A query cost applies only when measurements become available, not to polls/starts.
        components["measurement_cost"] = -self.reward_spec.measurement_cost * len(new_measurements)
        if not new_measurements:
            components["goal"] = components["improvement"] = 0.0
        if replayed:
            components = dict.fromkeys(components, 0.0)
        reward = sum(components.values())
        elapsed = self.runtime.clock_min - clock_before
        reason = (
            "target_reached"
            if success
            else "support_exhausted"
            if self.terminated
            else "measurement_budget"
            if len(self._measured) >= self.task.max_measurements
            else "time_limit"
            if self.runtime.clock_min >= self.task.max_time_min
            else "action_limit"
            if self.truncated
            else None
        )
        info = self._info(
            results,
            components,
            len(new_measurements),
            elapsed,
            new_measurements=new_measurements,
            termination_reason=reason,
        )
        self.last_outcome = copy.deepcopy(info)
        after = self.public_snapshot()
        try:
            serialized = action.to_dict()
            stable_hash(serialized)
        except (AttributeError, TypeError, ValueError):
            serialized = {"name": "invalid", "parameters": {}}
        self._trace.append(
            copy.deepcopy(
                {
                    "episode_id": self.episode_id,
                    "manifest_hash": self.manifest.manifest_hash,
                    "reset_count": self.reset_count,
                    "before": before,
                    "action": serialized,
                    "after": after,
                    "results": info["results"],
                    "endpoint_evidence": info["endpoint_evidence"],
                    "reward": reward,
                    "reward_components": components,
                    "failure_category": info["failure_category"],
                    "info": info,
                    "terminated": self.terminated,
                    "truncated": self.truncated,
                }
            )
        )
        return StepResult(self.observe(), reward, self.terminated, self.truncated, info)

    def trace(self):
        return copy.deepcopy(self._trace)

    def evaluate(self):
        optimum = max(m.conductivity_ms_cm for m in self._outcomes.values())
        target_index = next(
            (
                i
                for i, m in enumerate(self._measured.values(), 1)
                if m.conductivity_ms_cm >= self.task.target_conductivity
            ),
            None,
        )
        return {
            "task_id": self.task.task_id,
            "success": self._success(),
            "measurements": len(self._measured),
            "actions": self.step_count,
            "best_found_ms_cm": self._best(),
            "oracle_optimum_ms_cm": optimum,
            "simple_regret_ms_cm": optimum - self._best() if self._measured else None,
            "experiments_to_target": target_index,
            "actions_to_target": self._measurement_actions[target_index - 1]
            if target_index
            else None,
            "logical_time_min": self.runtime.clock_min,
            "total_query_cost": len(self._measured),
            "cost_source": "proxy",
            "cost_unit": "measurement_query",
            "scientifically_validated": False,
            "valid_action_rate": sum(e["info"]["failure_code"] is None for e in self._trace)
            / len(self._trace)
            if self._trace
            else 0.0,
        }

    def episode_outcome(self):
        endpoints = {
            name: any(
                e["present"]
                for t in self._trace
                for e in t["endpoint_evidence"]
                if e["endpoint"] == name
            )
            for name in ("plan_materialized", "dispatch_verified", "completed")
        }
        return EpisodeOutcome(
            endpoints["plan_materialized"],
            endpoints["dispatch_verified"],
            endpoints["completed"],
            False,
            False,
            False,
            self._success(),
            ("invalid_action",) if any(t["info"]["failure_code"] for t in self._trace) else (),
            sum(t["reward"] for t in self._trace),
            self.runtime.clock_min,
            float(len(self._measured)),
            tuple(sorted(self.runtime.artifacts)),
        )
