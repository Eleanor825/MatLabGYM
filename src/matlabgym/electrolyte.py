"""A small, deterministic electrolyte decision environment.

The fixture oracle is intentionally explicit: it is a demo/test oracle, not a
claim about real electrolyte behaviour.  A production deployment should load a
versioned replay table (or a validated physics/real-lab adapter) through the
same ``OutcomeOracle`` protocol.
"""

from __future__ import annotations

import copy
import csv
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .api import canonical_action, make_info
from .benchmark import EpisodeOutcome
from .core import Action, Observation, StepResult, TaskSpec, action_catalog
from .lab.contracts import stable_hash
from .rewards import ReplayRewardSpec


@dataclass(frozen=True)
class Formulation:
    formulation_id: str
    ec: Optional[float]
    pc: Optional[float]
    emc: Optional[float]
    salt_m: Optional[float]

    def to_dict(self) -> Dict[str, Union[float, str, None]]:
        return {
            "formulation_id": self.formulation_id,
            "ec": self.ec,
            "pc": self.pc,
            "emc": self.emc,
            "salt_m": self.salt_m,
        }


@dataclass(frozen=True)
class Measurement:
    formulation_id: str
    temperature_c: int
    conductivity_ms_cm: float
    uncertainty_ms_cm: Optional[float]
    source: str

    def to_dict(self) -> Dict[str, Union[float, int, str, None]]:
        return {
            "formulation_id": self.formulation_id,
            "temperature_c": self.temperature_c,
            "conductivity_ms_cm": self.conductivity_ms_cm,
            "uncertainty_ms_cm": self.uncertainty_ms_cm,
            "source": self.source,
        }


class OutcomeOracle:
    """Minimal protocol for replay, physics, hybrid, and real-lab backends."""

    def measure(self, formulation_id: str, temperature_c: int) -> Measurement:
        raise NotImplementedError

    def candidates(self) -> Sequence[Formulation]:
        raise NotImplementedError

    def supported_actions(self) -> Sequence[Tuple[str, int]]:
        raise NotImplementedError


class FixtureElectrolyteOracle(OutcomeOracle):
    """Deterministic analytic fixture used only for local smoke tests."""

    def __init__(self, formulations: Sequence[Formulation], source: str = "fixture-v0"):
        self._formulations = {f.formulation_id: f for f in formulations}
        self.source = source

    def candidates(self) -> Sequence[Formulation]:
        return tuple(self._formulations.values())

    def supported_actions(self) -> Sequence[Tuple[str, int]]:
        return tuple((formulation.formulation_id, 30) for formulation in self.candidates())

    def measure(self, formulation_id: str, temperature_c: int) -> Measurement:
        try:
            f = self._formulations[formulation_id]
        except KeyError as exc:
            raise KeyError(f"unknown formulation: {formulation_id}") from exc
        # Bounded fixture with a clear optimum, temperature dependence, and noise
        # reported as uncertainty rather than silently injected into truth.
        solvent_balance = 1.0 - abs(f.ec - 0.35) - 0.7 * abs(f.pc - 0.20)
        salt_term = math.exp(-((f.salt_m - 1.05) ** 2) / 0.20)
        thermal_term = math.exp(-((temperature_c - 30.0) ** 2) / 1800.0)
        conductivity = 3.2 + 10.5 * solvent_balance * salt_term * thermal_term
        return Measurement(
            formulation_id=formulation_id,
            temperature_c=temperature_c,
            conductivity_ms_cm=round(conductivity, 6),
            uncertainty_ms_cm=0.15,
            source=self.source,
        )


class CSVReplayOracle(OutcomeOracle):
    """Replay an audited table with columns used by the public contract.

    Required columns: ``formulation_id``, ``temperature_c``,
    ``conductivity_ms_cm``.  ``uncertainty_ms_cm`` and ``source`` are optional.
    """

    def __init__(
        self,
        rows: Iterable[Mapping[str, str]],
        source: str = "csv-replay",
        duplicate_policy: str = "error",
    ):
        if duplicate_policy not in {"error", "first"}:
            raise ValueError("duplicate_policy must be 'error' or 'first'")
        self.source = source
        self._rows: Dict[Tuple[str, int], Measurement] = {}
        self._replicates: Dict[Tuple[str, int], List[Measurement]] = {}
        self._formulations: Dict[str, Formulation] = {}
        for row in rows:
            temperature = float(row["temperature_c"])
            if not math.isfinite(temperature) or not temperature.is_integer():
                raise ValueError(
                    "temperature_c must be an integer; fractional temperatures are unsupported"
                )
            key = (str(row["formulation_id"]), int(temperature))
            if not key[0].strip():
                raise ValueError("formulation_id must be non-empty")
            uncertainty_text = str(row.get("uncertainty_ms_cm", "")).strip()
            measurement = Measurement(
                formulation_id=key[0],
                temperature_c=key[1],
                conductivity_ms_cm=float(row["conductivity_ms_cm"]),
                uncertainty_ms_cm=float(uncertainty_text) if uncertainty_text else None,
                source=str(row.get("source", source)),
            )
            if not math.isfinite(measurement.conductivity_ms_cm):
                raise ValueError("conductivity must be finite")
            if measurement.uncertainty_ms_cm is not None and (
                not math.isfinite(measurement.uncertainty_ms_cm)
                or measurement.uncertainty_ms_cm < 0
            ):
                raise ValueError("uncertainty must be finite and non-negative")
            if key in self._rows:
                if duplicate_policy == "error":
                    raise ValueError("duplicate replay key: %s" % (key,))
                self._replicates.setdefault(key, [self._rows[key]])
                self._replicates[key].append(measurement)
                continue
            self._rows[key] = measurement
            if key[0] not in self._formulations:

                def optional_float(
                    name: str, source_row: Mapping[str, str] = row
                ) -> Optional[float]:
                    text = str(source_row.get(name, "")).strip()
                    return float(text) if text else None

                self._formulations[key[0]] = Formulation(
                    key[0],
                    optional_float("ec"),
                    optional_float("pc"),
                    optional_float("emc"),
                    optional_float("salt_m"),
                )

    @classmethod
    def from_csv(cls, path: Union[str, Path], source: str = "csv-replay") -> "CSVReplayOracle":
        with Path(path).open(newline="") as handle:
            return cls(csv.DictReader(handle), source=source)

    def candidates(self) -> Sequence[Formulation]:
        return tuple(self._formulations.values())

    def supported_actions(self) -> Sequence[Tuple[str, int]]:
        return tuple(sorted(self._rows))

    def replicates(self, formulation_id: str, temperature_c: int) -> Sequence[Measurement]:
        key = (formulation_id, temperature_c)
        if key not in self._rows:
            return ()
        return tuple(self._replicates.get(key, [self._rows[key]]))

    def measure(self, formulation_id: str, temperature_c: int) -> Measurement:
        key = (formulation_id, temperature_c)
        if key not in self._rows:
            raise KeyError(f"no measured outcome for {formulation_id} at {temperature_c} C")
        return self._rows[key]


def make_fixture_task() -> Tuple[TaskSpec, FixtureElectrolyteOracle]:
    formulations = [
        Formulation("E01", 0.30, 0.25, 0.45, 0.80),
        Formulation("E02", 0.35, 0.20, 0.45, 1.05),
        Formulation("E03", 0.40, 0.15, 0.45, 1.20),
        Formulation("E04", 0.20, 0.35, 0.45, 1.00),
        Formulation("E05", 0.45, 0.10, 0.45, 0.65),
        Formulation("E06", 0.25, 0.25, 0.50, 1.35),
    ]
    return (
        TaskSpec(
            task_id="electrolyte.fixture.conductivity.v0",
            goal="Find a formulation with conductivity at least 12.0 mS/cm at 30 C within 5 measurements.",
            max_steps=5,
            budget=5,
            required_target=12.0,
        ),
        FixtureElectrolyteOracle(formulations),
    )


@dataclass(frozen=True)
class ReplayManifest:
    task: TaskSpec
    reward: ReplayRewardSpec
    oracle_snapshot_hash: str
    temperature_c: int
    backend: str = "deterministic-replay"
    evaluator_version: str = "conductivity-support-evaluator-v2"
    schema_version: str = "2.0"
    cost_source: str = "proxy"
    cost_unit: str = "measurement_query"
    calibration_status: str = "unvalidated"

    def to_dict(self) -> dict:
        return {
            "task": self.task.to_dict(),
            "reward": self.reward.to_dict(),
            "oracle_snapshot_hash": self.oracle_snapshot_hash,
            "temperature_c": self.temperature_c,
            "backend": self.backend,
            "evaluator_version": self.evaluator_version,
            "schema_version": self.schema_version,
            "cost_source": self.cost_source,
            "cost_unit": self.cost_unit,
            "calibration_status": self.calibration_status,
        }

    @property
    def manifest_hash(self) -> str:
        return stable_hash(self.to_dict())


class ElectrolyteReplayEnv:
    """Finite-support experiments with configurable rewards and audited outcomes.

    Only observations are public. The in-process implementation is not a sandbox
    for an agent with arbitrary Python/file access. Oracle snapshots are frozen
    at construction; CSV input alone does not establish scientific calibration.
    """

    def __init__(
        self,
        task: TaskSpec,
        oracle: OutcomeOracle,
        seed: int = 0,
        temperature_c: int = 30,
        *,
        reward: Optional[ReplayRewardSpec] = None,
    ):
        for name in ("max_steps", "budget"):
            value = getattr(task, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("%s must be a positive integer" % name)
        if task.required_target is not None and (
            isinstance(task.required_target, bool) or not math.isfinite(task.required_target)
        ):
            raise ValueError("required_target must be finite")
        if isinstance(temperature_c, bool) or not isinstance(temperature_c, int):
            raise ValueError("temperature_c must be an integer")
        self.task = task
        self.oracle = oracle
        self.seed = seed
        self.temperature_c = temperature_c
        self.reward_spec = reward or ReplayRewardSpec.improvement(
            scale=abs(task.required_target) if task.required_target else 1.0
        )
        if not isinstance(self.reward_spec, ReplayRewardSpec):
            raise ValueError("reward must be a ReplayRewardSpec")
        self._candidates = tuple(copy.deepcopy(oracle.candidates()))
        self._outcomes = {}
        for key in oracle.supported_actions():
            if key[1] != temperature_c:
                continue
            measurement = copy.deepcopy(oracle.measure(*key))
            if (measurement.formulation_id, measurement.temperature_c) != key:
                raise ValueError("oracle measurement does not match requested action")
            if not math.isfinite(measurement.conductivity_ms_cm):
                raise ValueError("conductivity must be finite")
            if measurement.uncertainty_ms_cm is not None and (
                not math.isfinite(measurement.uncertainty_ms_cm)
                or measurement.uncertainty_ms_cm < 0
            ):
                raise ValueError("uncertainty must be finite and non-negative")
            self._outcomes[key] = measurement
        if not self._outcomes:
            raise ValueError("oracle has no supported outcomes at configured temperature")
        # Fail before starting an episode if the chosen scale/weights overflow
        # anywhere in this frozen support. Do not partially consume a query.
        for measurement in self._outcomes.values():
            self.reward_spec.components(
                valid=True,
                previous_best=None,
                current_best=measurement.conductivity_ms_cm,
                goal_reached=True,
            )
        self.manifest = ReplayManifest(
            task,
            self.reward_spec,
            stable_hash(
                {
                    "candidates": [f.to_dict() for f in self._candidates],
                    "measurements": [self._outcomes[k].to_dict() for k in sorted(self._outcomes)],
                }
            ),
            temperature_c,
            backend="analytic-fixture"
            if isinstance(oracle, FixtureElectrolyteOracle)
            else "deterministic-replay",
        )
        self.reset(seed=seed)

    @property
    def budget_spec(self) -> dict:
        return {"max_steps": self.task.max_steps, "budget": self.task.budget}

    def reset(self, *, seed: Optional[int] = None, options=None):
        if options:
            raise ValueError("construct a new environment to change task, oracle or reward")
        if self.task != self.manifest.task or self.reward_spec != self.manifest.reward:
            raise ValueError("task/reward differs from frozen manifest")
        if self.temperature_c != self.manifest.temperature_c:
            raise ValueError("temperature differs from frozen manifest")
        if seed is not None:
            self.seed = seed
        self._rng = random.Random(self.seed)
        # IDs are local to a deterministic episode, not globally unique workspaces.
        self.episode_id = "replay-%s" % self.seed
        self.step_count = 0
        self.budget_remaining = self.task.budget
        self.measured: Dict[Tuple[str, int], Measurement] = {}
        self.best_measurement: Optional[Measurement] = None
        self.last_outcome = None
        self.terminated = False
        self.truncated = False
        self._trace = []
        return self.observe(), make_info(
            episode_id=self.episode_id,
            manifest_hash=self.manifest.manifest_hash,
            public_state=self.public_snapshot(),
            backend=self.manifest.backend,
            **{
                "seed": self.seed,
                "reward_version": self.reward_spec.version,
                "workspace_policy": "in_memory_episode_isolation",
                "cost_source": "proxy",
                "cost_unit": "measurement_query",
                "calibration_status": "unvalidated",
            },
        )

    def public_snapshot(self) -> dict:
        return self.observe().public_state

    def action_specs(self):
        return (
            {
                "name": "measure_conductivity",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["formulation_id", "temperature_c"],
                    "properties": {
                        "formulation_id": {
                            "type": "string",
                            "enum": sorted({k[0] for k in self._outcomes}),
                        },
                        "temperature_c": {"type": "integer", "enum": [self.temperature_c]},
                    },
                },
            },
        )

    def available_actions(self) -> List[Action]:
        if self.terminated or self.truncated:
            return []
        return [
            Action("measure_conductivity", {"formulation_id": key[0], "temperature_c": key[1]})
            for key in sorted(self._outcomes)
            if key not in self.measured
        ]

    def observe(self) -> Observation:
        return Observation(
            step=self.step_count,
            budget_remaining=self.budget_remaining,
            available_actions=action_catalog(self.available_actions()),
            public_state={
                "task_id": self.task.task_id,
                "goal": self.task.goal,
                "candidates": [f.to_dict() for f in self._candidates],
                "measured_keys": [list(k) for k in sorted(self.measured)],
                "measurements": [self.measured[k].to_dict() for k in sorted(self.measured)],
                "best_so_far_ms_cm": self.best_measurement.conductivity_ms_cm
                if self.best_measurement
                else None,
                "support_size": len(self._outcomes),
                "support_mask": [list(k) for k in sorted(self._outcomes)],
                "step": self.step_count,
                "budget_remaining": self.budget_remaining,
                "terminated": self.terminated,
                "truncated": self.truncated,
            },
            last_outcome=copy.deepcopy(self.last_outcome),
        )

    def step(self, action: Action) -> StepResult:
        if self.terminated or self.truncated:
            raise RuntimeError("episode is finished; call reset()")
        action = canonical_action(action)
        if self.task != self.manifest.task or self.reward_spec != self.manifest.reward:
            raise ValueError("task/reward differs from frozen manifest")
        if self.temperature_c != self.manifest.temperature_c:
            raise ValueError("temperature differs from frozen manifest")
        before = self.observe().public_state
        previous_best = self.best_measurement.conductivity_ms_cm if self.best_measurement else None
        info = {"valid": False, "failure_reason": None, "failure_code": None}
        try:
            if action.name != "measure_conductivity":
                raise ValueError("unknown action")
            parameters = action.parameters
            if not isinstance(parameters, Mapping):
                raise ValueError("parameters must be an object")
            if set(parameters) != {"formulation_id", "temperature_c"}:
                raise ValueError("expected formulation_id and temperature_c")
            formulation_id = parameters["formulation_id"]
            temperature_c = parameters["temperature_c"]
            if not isinstance(formulation_id, str):
                raise ValueError("formulation_id must be a string")
            if isinstance(temperature_c, bool) or not isinstance(temperature_c, int):
                raise ValueError("temperature_c must be an integer")
            key = (formulation_id, temperature_c)
            if key in self.measured:
                raise ValueError("measurement already consumed")
            if key not in self._outcomes:
                raise ValueError("action outside measured support")
            measurement = self._outcomes[key]
            self.measured[key] = measurement
            if self.best_measurement is None or (
                measurement.conductivity_ms_cm > self.best_measurement.conductivity_ms_cm
            ):
                self.best_measurement = measurement
            self.budget_remaining -= 1
            # A successful query has a unit proxy cost, independent of reward weights.
            info.update({"valid": True, "measurement": measurement.to_dict()})
        except (KeyError, TypeError, ValueError) as exc:
            info.update({"failure_reason": str(exc), "failure_code": "INVALID_ACTION"})
        self.step_count += 1
        best = self.best_measurement.conductivity_ms_cm if self.best_measurement else None
        success = (
            self.task.required_target is not None
            and best is not None
            and (best >= self.task.required_target)
        )
        exhausted_support = len(self.measured) == len(self._outcomes)
        self.terminated = success or exhausted_support
        self.truncated = not self.terminated and (
            self.budget_remaining <= 0 or self.step_count >= self.task.max_steps
        )
        components = self.reward_spec.components(
            valid=info["valid"],
            previous_best=previous_best,
            current_best=best,
            goal_reached=success,
        )
        reward = sum(components.values())
        info.update(
            {
                "success": success,
                "endpoint": "completed" if info["valid"] else "invalid_action",
                "reward_components": components,
                "reward_version": self.reward_spec.version,
                "manifest_hash": self.manifest.manifest_hash,
                "episode_id": self.episode_id,
                "cost_source": "proxy",
                "cost_unit": "measurement_query",
                "query_cost": int(info["valid"]),
                "total_cost": len(self.measured),
                "calibration_status": "unvalidated",
                "termination_reason": "target_reached"
                if success
                else "support_exhausted"
                if exhausted_support
                else "budget_exhausted"
                if self.budget_remaining <= 0
                else "action_limit"
                if self.truncated
                else None,
            }
        )
        artifact_id = "measurement-%s-%d" % (self.episode_id, len(self.measured))
        results = [
            {
                "success": info["valid"],
                "status": info["endpoint"],
                "measurement": info.get("measurement"),
                "failure_code": info["failure_code"],
                "produced_artifact_ids": [artifact_id] if info["valid"] else [],
            }
        ]
        evidence = [
            {
                "endpoint": "completed",
                "present": info["valid"],
                "evidence_source": self.manifest.backend,
                "artifact_refs": [artifact_id] if info["valid"] else [],
            },
            {
                "endpoint": "scientifically_validated",
                "present": False,
                "evidence_source": "no_registered_calibration",
                "artifact_refs": [],
            },
        ]
        info.update(
            {
                "results": results,
                "endpoint_evidence": evidence,
                "failure_category": None if info["valid"] else "invalid_action",
            }
        )
        self.last_outcome = copy.deepcopy(info)
        after = self.observe().public_state
        info["state_hash"] = stable_hash(after)
        extensions = {
            k: v
            for k, v in info.items()
            if k
            not in {
                "episode_id",
                "manifest_hash",
                "state_hash",
                "results",
                "reward_components",
                "failure_code",
            }
        }
        info = make_info(
            episode_id=self.episode_id,
            manifest_hash=self.manifest.manifest_hash,
            public_state=after,
            backend=self.manifest.backend,
            results=results,
            reward_components=components,
            failure_code=info["failure_code"],
            costs=[
                {"quantity": int(info["valid"]), "unit": "measurement_query", "source": "proxy"}
            ],
            **extensions,
        )
        results = info["results"]
        self.last_outcome = copy.deepcopy(info)
        try:
            serialized_action = json.loads(json.dumps(action.to_dict(), allow_nan=False))
        except (TypeError, ValueError):
            serialized_action = {"name": str(action.name), "parameters": {"_invalid_payload": True}}
        self._trace.append(
            copy.deepcopy(
                {
                    "episode_id": self.episode_id,
                    "manifest_hash": self.manifest.manifest_hash,
                    "before": before,
                    "action": serialized_action,
                    "after": after,
                    "info": info,
                    "results": results,
                    "endpoint_evidence": evidence,
                    "failure_category": info["failure_category"],
                    "reward": reward,
                    "reward_components": components,
                    "terminated": self.terminated,
                    "truncated": self.truncated,
                }
            )
        )
        return StepResult(
            self.observe(), reward, self.terminated, self.truncated, copy.deepcopy(info)
        )

    def trace(self) -> List[Dict[str, object]]:
        return copy.deepcopy(self._trace)

    def replay(self, trace: Sequence[Mapping[str, object]]) -> Observation:
        self.reset(seed=self.seed)
        for event in trace:
            action_data = event["action"]
            self.step(Action(str(action_data["name"]), dict(action_data["parameters"])))
        return self.observe()

    def evaluate(self) -> Dict[str, object]:
        # This is an evaluator-only full-support query; never included in observations.
        optimum = max(m.conductivity_ms_cm for m in self._outcomes.values())
        best = self.best_measurement.conductivity_ms_cm if self.best_measurement else None
        target = self.task.required_target
        target_experiment = None
        target_action = None
        valid_count = 0
        for index, event in enumerate(self._trace, start=1):
            if not event["info"]["valid"]:
                continue
            valid_count += 1
            if (
                target_experiment is None
                and target is not None
                and (event["info"]["measurement"]["conductivity_ms_cm"] >= target)
            ):
                target_experiment, target_action = valid_count, index
        return {
            "task_id": self.task.task_id,
            "seed": self.seed,
            "success": bool(target is not None and best is not None and best >= target),
            "best_found_ms_cm": best,
            "oracle_optimum_ms_cm": optimum,
            "support_size": len(self._outcomes),
            "simple_regret_ms_cm": None if best is None else optimum - best,
            "experiments_to_target": target_experiment,
            "actions_to_target": target_action,
            "measurements": valid_count,
            "valid_action_rate": valid_count / len(self._trace) if self._trace else 0.0,
            "steps": len(self._trace),
            "budget_remaining": self.budget_remaining,
            "cost_source": "proxy",
            "cost_unit": "measurement_query",
            "scientifically_validated": False,
        }

    def episode_outcome(self) -> EpisodeOutcome:
        return EpisodeOutcome(
            logical_plan_materialized=False,
            logical_dispatch_verified=False,
            logical_completed=bool(self.measured),
            physical_started=False,
            physical_completed=False,
            scientifically_validated=False,
            goal_reached=self.evaluate()["success"],
            failure_categories=("invalid_action",)
            if any(not e["info"]["valid"] for e in self._trace)
            else (),
            total_reward=sum(e["reward"] for e in self._trace),
            logical_time_min=0.0,
            total_cost=float(len(self.measured)),
            artifact_refs=tuple(
                artifact
                for e in self._trace
                for result in e["results"]
                for artifact in result["produced_artifact_ids"]
            ),
        )
