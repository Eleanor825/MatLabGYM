"""A tiny state-transition environment for long-horizon workflow planning."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional

from .api import canonical_action, make_info
from .benchmark import EpisodeOutcome, stable_hash
from .core import Action, Observation, StepResult, TaskSpec


@dataclass(frozen=True)
class PlanningManifest:
    task: TaskSpec
    backend: str = "deterministic-planning"
    schema_version: str = "1.0"
    evaluator_version: str = "planning-workflow-v1"

    def to_dict(self):
        return {
            "task": self.task.to_dict(),
            "backend": self.backend,
            "schema_version": self.schema_version,
            "evaluator_version": self.evaluator_version,
        }

    @property
    def manifest_hash(self):
        return stable_hash(self.to_dict())


@dataclass
class PlanningState:
    electrolyte_prepared: bool = False
    cell_assembled: bool = False
    formed: bool = False
    cycled: bool = False
    characterized: bool = False


class PlanningEnv:
    """Deterministic validator for a five-stage cell workflow.

    It intentionally does not simulate electrochemistry.  Its job is to prove
    that the plan/transition layer can reject impossible sequences and reach a
    terminal goal without exact-match to one reference plan.
    """

    def __init__(self, max_steps: int = 12):
        self.task = TaskSpec(
            "planning.fixture.cell_workflow.v0",
            "Prepare, assemble, form, cycle, and characterize a cell.",
            max_steps,
            max_steps,
        )
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
        self.max_steps = max_steps
        self.manifest = PlanningManifest(self.task)
        self.reset()

    @property
    def budget_spec(self):
        return {"max_steps": self.task.max_steps, "budget": self.task.budget}

    def reset(self, *, seed=None, options=None):
        if options:
            raise ValueError("reset options are not supported")
        self.seed = int(seed or 0)
        self.episode_id = "planning-ep-%d" % self.seed
        self._trace = []
        self.state = PlanningState()
        self.step_count = 0
        self.last_outcome: Optional[Mapping[str, object]] = None
        self.terminated = False
        self.truncated = False
        return self.observe(), make_info(
            episode_id=self.episode_id,
            manifest_hash=self.manifest.manifest_hash,
            public_state=self.public_snapshot(),
            backend=self.manifest.backend,
            seed=self.seed,
        )

    def public_snapshot(self):
        return deepcopy(self.state.__dict__)

    def action_specs(self):
        return tuple(
            {
                "name": action.name,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            }
            for action in self._actions()
        )

    def trace(self):
        return deepcopy(self._trace)

    def _actions(self) -> List[Action]:
        return [
            Action("prepare_electrolyte"),
            Action("assemble_cell"),
            Action("formation"),
            Action("cycle"),
            Action("characterize"),
        ]

    def observe(self) -> Observation:
        return Observation(
            self.step_count,
            self.max_steps - self.step_count,
            self.action_specs(),
            self.public_snapshot(),
            deepcopy(self.last_outcome),
        )

    def step(self, action: Action) -> StepResult:
        if self.terminated or self.truncated:
            raise RuntimeError("episode is finished; call reset()")
        action = canonical_action(action)
        before = self.state.__dict__.copy()
        outcome: Dict[str, object] = {
            "valid": False,
            "endpoint": "invalid_action",
            "failure_reason": None,
        }
        dependencies = {
            "prepare_electrolyte": (None, "electrolyte_prepared"),
            "assemble_cell": ("electrolyte_prepared", "cell_assembled"),
            "formation": ("cell_assembled", "formed"),
            "cycle": ("formed", "cycled"),
            "characterize": ("cycled", "characterized"),
        }
        if action.parameters:
            outcome["failure_reason"] = "planning actions do not accept parameters"
        elif action.name not in dependencies:
            outcome["failure_reason"] = f"unknown skill: {action.name}"
        else:
            prerequisite, effect = dependencies[action.name]
            if prerequisite is not None and not getattr(self.state, prerequisite):
                outcome["failure_reason"] = f"precondition failed: {prerequisite} is false"
            elif getattr(self.state, effect):
                outcome["failure_reason"] = f"state effect already applied: {effect}"
            else:
                setattr(self.state, effect, True)
                outcome.update({"valid": True, "endpoint": "completed", "state_effect": effect})
        self.step_count += 1
        if self.state.characterized:
            self.terminated = True
            outcome["success"] = True
        elif self.step_count >= self.max_steps:
            self.truncated = True
            outcome["success"] = False
        reward = 1.0 if outcome["valid"] else -1.0
        if outcome.get("success"):
            reward += 5.0
        after = self.public_snapshot()
        components = {
            "transition": 1.0 if outcome["valid"] else -1.0,
            "goal": 5.0 if outcome.get("success") else 0.0,
        }
        results = [
            {
                "success": outcome["valid"],
                "status": "completed" if outcome["valid"] else "rejected",
                "failure_code": None if outcome["valid"] else "INVALID_ACTION",
                "produced_artifact_ids": [],
                **outcome,
            }
        ]
        info = make_info(
            episode_id=self.episode_id,
            manifest_hash=self.manifest.manifest_hash,
            public_state=after,
            backend=self.manifest.backend,
            results=results,
            reward_components=components,
            failure_code=results[0]["failure_code"],
            costs=[{"quantity": 1, "unit": "action", "source": "proxy"}],
            before=before,
            after=after,
            endpoint_evidence=[],
            **outcome,
        )
        self.last_outcome = deepcopy(info)
        self._trace.append(
            deepcopy(
                {
                    "index": len(self._trace),
                    "episode_id": self.episode_id,
                    "manifest_hash": self.manifest.manifest_hash,
                    "before": before,
                    "after": after,
                    "action": action.to_dict(),
                    "results": info["results"],
                    "endpoint_evidence": [],
                    "failure_category": None if outcome["valid"] else "invalid_action",
                    "reward": reward,
                    "reward_components": components,
                    "terminated": self.terminated,
                    "truncated": self.truncated,
                    "info": info,
                }
            )
        )
        return StepResult(self.observe(), reward, self.terminated, self.truncated, info)

    def evaluate(self):
        events = self.trace()
        completed = sum(bool(event["results"][0]["success"]) for event in events)
        success = bool(events and events[-1]["after"]["characterized"])
        return {
            "task_id": self.task.task_id,
            "seed": self.seed,
            "success": success,
            "steps": len(events),
            "completed_stages": completed,
            "valid_action_rate": completed / len(events) if events else 0.0,
            "total_reward": sum(event["reward"] for event in events),
            "scientifically_validated": False,
        }

    def episode_outcome(self):
        report = self.evaluate()
        return EpisodeOutcome(
            logical_plan_materialized=report["completed_stages"] > 0,
            logical_dispatch_verified=False,
            logical_completed=report["success"],
            physical_started=False,
            physical_completed=False,
            scientifically_validated=False,
            goal_reached=report["success"],
            failure_categories=("invalid_action",)
            if any(e["failure_category"] for e in self._trace)
            else (),
            total_reward=report["total_reward"],
            logical_time_min=0.0,
            total_cost=float(report["steps"]),
            artifact_refs=(),
        )
