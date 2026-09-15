"""A tiny state-transition environment for long-horizon workflow planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional

from .core import Action, Observation, StepResult, TaskSpec, action_catalog


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
        self.task = TaskSpec("planning.fixture.cell_workflow.v0", "Prepare, assemble, form, cycle, and characterize a cell.", max_steps, max_steps)
        self.max_steps = max_steps
        self.reset()

    def reset(self) -> Observation:
        self.state = PlanningState()
        self.step_count = 0
        self.last_outcome: Optional[Mapping[str, object]] = None
        self.terminated = False
        self.truncated = False
        return self.observe()

    def _actions(self) -> List[Action]:
        return [
            Action("prepare_electrolyte"),
            Action("assemble_cell"),
            Action("formation"),
            Action("cycle"),
            Action("characterize"),
        ]

    def observe(self) -> Observation:
        return Observation(self.step_count, self.max_steps - self.step_count, action_catalog(self._actions()), self.state.__dict__.copy(), self.last_outcome)

    def step(self, action: Action) -> StepResult:
        if self.terminated or self.truncated:
            raise RuntimeError("episode is finished; call reset()")
        before = self.state.__dict__.copy()
        outcome: Dict[str, object] = {"valid": False, "endpoint": "invalid_action", "failure_reason": None}
        dependencies = {
            "prepare_electrolyte": (None, "electrolyte_prepared"),
            "assemble_cell": ("electrolyte_prepared", "cell_assembled"),
            "formation": ("cell_assembled", "formed"),
            "cycle": ("formed", "cycled"),
            "characterize": ("cycled", "characterized"),
        }
        if action.name not in dependencies:
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
        self.last_outcome = outcome
        reward = 1.0 if outcome["valid"] else -1.0
        if outcome.get("success"):
            reward += 5.0
        info = {"before": before, "after": self.state.__dict__.copy(), **outcome}
        return StepResult(self.observe(), reward, self.terminated, self.truncated, info)
