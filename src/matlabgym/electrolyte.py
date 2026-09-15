"""A small, deterministic electrolyte decision environment.

The fixture oracle is intentionally explicit: it is a demo/test oracle, not a
claim about real electrolyte behaviour.  A production deployment should load a
versioned replay table (or a validated physics/real-lab adapter) through the
same ``OutcomeOracle`` protocol.
"""

from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .core import Action, Observation, StepResult, TaskSpec, action_catalog


@dataclass(frozen=True)
class Formulation:
    formulation_id: str
    ec: float
    pc: float
    emc: float
    salt_m: float

    def to_dict(self) -> Dict[str, Union[float, str]]:
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
    uncertainty_ms_cm: float
    source: str

    def to_dict(self) -> Dict[str, Union[float, int, str]]:
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


class FixtureElectrolyteOracle(OutcomeOracle):
    """Deterministic analytic fixture used only for local smoke tests."""

    def __init__(self, formulations: Sequence[Formulation], source: str = "fixture-v0"):
        self._formulations = {f.formulation_id: f for f in formulations}
        self.source = source

    def candidates(self) -> Sequence[Formulation]:
        return tuple(self._formulations.values())

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

    def __init__(self, rows: Iterable[Mapping[str, str]], source: str = "csv-replay"):
        self.source = source
        self._rows: Dict[Tuple[str, int], Measurement] = {}
        self._formulations: Dict[str, Formulation] = {}
        for row in rows:
            key = (str(row["formulation_id"]), int(float(row["temperature_c"])))
            self._rows[key] = Measurement(
                formulation_id=key[0],
                temperature_c=key[1],
                conductivity_ms_cm=float(row["conductivity_ms_cm"]),
                uncertainty_ms_cm=float(row.get("uncertainty_ms_cm", "nan")),
                source=str(row.get("source", source)),
            )
            if key[0] not in self._formulations:
                self._formulations[key[0]] = Formulation(key[0], float("nan"), float("nan"), float("nan"), float("nan"))

    @classmethod
    def from_csv(cls, path: Union[str, Path], source: str = "csv-replay") -> "CSVReplayOracle":
        with Path(path).open(newline="") as handle:
            return cls(csv.DictReader(handle), source=source)

    def candidates(self) -> Sequence[Formulation]:
        return tuple(self._formulations.values())

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


class ElectrolyteReplayEnv:
    """Gym-like replay environment with hidden outcomes and audit traces."""

    def __init__(self, task: TaskSpec, oracle: OutcomeOracle, seed: int = 0, temperature_c: int = 30):
        self.task = task
        self.oracle = oracle
        self.seed = seed
        self.temperature_c = temperature_c
        self._rng = random.Random(seed)
        self._trace: List[Dict[str, object]] = []
        self.reset(seed)

    def reset(self, seed: Optional[int] = None) -> Observation:
        if seed is not None:
            self.seed = seed
        self._rng = random.Random(self.seed)
        self.step_count = 0
        self.budget_remaining = self.task.budget
        self.measured: Dict[Tuple[str, int], Measurement] = {}
        self.best_measurement: Optional[Measurement] = None
        self.last_outcome: Optional[Mapping[str, object]] = None
        self.terminated = False
        self.truncated = False
        self._trace = []
        return self.observe()

    def available_actions(self) -> List[Action]:
        actions = []
        for formulation in self.oracle.candidates():
            key = (formulation.formulation_id, self.temperature_c)
            if key not in self.measured:
                actions.append(Action("measure_conductivity", {"formulation_id": formulation.formulation_id, "temperature_c": self.temperature_c}))
        return actions

    def observe(self) -> Observation:
        public_candidates = [f.to_dict() for f in self.oracle.candidates()]
        public_state = {
            "task_id": self.task.task_id,
            "goal": self.task.goal,
            "candidates": public_candidates,
            "measured_keys": [list(k) for k in sorted(self.measured)],
            "best_so_far_ms_cm": self.best_measurement.conductivity_ms_cm if self.best_measurement else None,
        }
        return Observation(
            step=self.step_count,
            budget_remaining=self.budget_remaining,
            available_actions=action_catalog(self.available_actions()),
            public_state=public_state,
            last_outcome=self.last_outcome,
        )

    def step(self, action: Action) -> StepResult:
        if self.terminated or self.truncated:
            raise RuntimeError("episode is finished; call reset()")
        before = self.observe().to_dict()
        info: Dict[str, object] = {"valid": False, "failure_reason": None, "endpoint": "execution"}
        reward = 0.0
        key: Optional[Tuple[str, int]] = None
        try:
            if action.name != "measure_conductivity":
                raise ValueError("unknown action")
            formulation_id = str(action.parameters["formulation_id"])
            temperature_c = int(action.parameters["temperature_c"])
            key = (formulation_id, temperature_c)
            if temperature_c != self.temperature_c:
                raise ValueError(f"temperature must be {self.temperature_c} C in fixture task")
            if key in self.measured:
                raise ValueError("measurement already consumed")
            measurement = self.oracle.measure(formulation_id, temperature_c)
            self.measured[key] = measurement
            if self.best_measurement is None or measurement.conductivity_ms_cm > self.best_measurement.conductivity_ms_cm:
                self.best_measurement = measurement
            self.budget_remaining -= 1
            self.step_count += 1
            info.update({"valid": True, "measurement": measurement.to_dict(), "endpoint": "completed"})
            reward = measurement.conductivity_ms_cm / (self.task.required_target or 1.0)
            if self.task.required_target is not None and measurement.conductivity_ms_cm >= self.task.required_target:
                self.terminated = True
                info["success"] = True
                reward += 1.0
            elif self.budget_remaining <= 0 or self.step_count >= self.task.max_steps:
                self.terminated = True
                info["success"] = False
        except (KeyError, TypeError, ValueError) as exc:
            self.step_count += 1
            info["failure_reason"] = str(exc)
            info["endpoint"] = "invalid_action"
            reward = -1.0
            if self.step_count >= self.task.max_steps:
                self.truncated = True
        self.last_outcome = info
        after = self.observe().to_dict()
        self._trace.append({"before": before, "action": action.to_dict(), "after": after, "info": dict(info), "reward": reward})
        return StepResult(self.observe(), reward, self.terminated, self.truncated, info)

    def trace(self) -> List[Dict[str, object]]:
        return json.loads(json.dumps(self._trace))

    def replay(self, trace: Sequence[Mapping[str, object]]) -> Observation:
        self.reset(self.seed)
        for event in trace:
            action_data = event["action"]
            self.step(Action(str(action_data["name"]), dict(action_data["parameters"])))
        return self.observe()

    def evaluate(self) -> Dict[str, object]:
        all_measurements = [self.oracle.measure(f.formulation_id, self.temperature_c) for f in self.oracle.candidates()]
        optimum = max(m.conductivity_ms_cm for m in all_measurements)
        best = self.best_measurement.conductivity_ms_cm if self.best_measurement else None
        target = self.task.required_target
        target_step = None
        for index, event in enumerate(self._trace, start=1):
            if event["info"].get("valid") and event["info"].get("measurement", {}).get("conductivity_ms_cm", -math.inf) >= (target or math.inf):
                target_step = index
                break
        valid_count = sum(1 for event in self._trace if event["info"].get("valid"))
        return {
            "task_id": self.task.task_id,
            "seed": self.seed,
            "success": bool(target is not None and best is not None and best >= target),
            "best_found_ms_cm": best,
            "oracle_optimum_ms_cm": optimum,
            "simple_regret_ms_cm": None if best is None else optimum - best,
            "experiments_to_target": target_step,
            "valid_action_rate": valid_count / len(self._trace) if self._trace else 0.0,
            "steps": len(self._trace),
            "budget_remaining": self.budget_remaining,
        }
