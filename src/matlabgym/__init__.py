"""MatLabGYM: verifiable environments for materials-science agents."""

from .core import Action, Observation, StepResult, TaskSpec
from .domains import build_electrolyte_line_env, build_electrolyte_registry
from .electrolyte import ElectrolyteReplayEnv, make_fixture_task
from .lab import LabGymEnv, LabRuntime, SkillRegistry
from .planning import PlanningEnv

__all__ = [
    "Action",
    "Observation",
    "StepResult",
    "TaskSpec",
    "ElectrolyteReplayEnv",
    "LabGymEnv",
    "LabRuntime",
    "PlanningEnv",
    "SkillRegistry",
    "build_electrolyte_line_env",
    "build_electrolyte_registry",
    "make_fixture_task",
]
