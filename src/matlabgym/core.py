"""Shared, serialisable contracts used by every MatLabGYM backend.

The contracts deliberately keep the scientific outcome separate from the task
reward.  This makes it possible to replace the fixture oracle with a replay,
physics, hybrid, or real-lab adapter without changing the agent-facing API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Action:
    """An agent action.  Parameters must be JSON-compatible values."""

    name: str
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "parameters": dict(self.parameters)}


@dataclass(frozen=True)
class TaskSpec:
    """Versioned task contract and deterministic success predicate inputs."""

    task_id: str
    goal: str
    max_steps: int
    budget: int
    required_target: Optional[float] = None
    version: str = "0.1"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Observation:
    """What the agent is allowed to see at a timestep."""

    step: int
    budget_remaining: int
    available_actions: Tuple[Dict[str, Any], ...]
    public_state: Mapping[str, Any]
    last_outcome: Optional[Mapping[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "budget_remaining": self.budget_remaining,
            "available_actions": list(self.available_actions),
            "public_state": dict(self.public_state),
            "last_outcome": dict(self.last_outcome) if self.last_outcome else None,
        }


@dataclass(frozen=True)
class StepResult:
    """A transition with enough information for audit and replay."""

    observation: Observation
    reward: float
    terminated: bool
    truncated: bool
    info: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation": self.observation.to_dict(),
            "reward": self.reward,
            "terminated": self.terminated,
            "truncated": self.truncated,
            "info": dict(self.info),
        }


def action_catalog(actions: Sequence[Action]) -> Tuple[Dict[str, Any], ...]:
    return tuple(action.to_dict() for action in actions)
