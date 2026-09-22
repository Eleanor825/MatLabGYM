"""MatLabGYM: verifiable environments for materials-science agents."""

from .benchmark import (
    BenchmarkManifest,
    DatasetSplit,
    EndpointEvidence,
    EndpointName,
    FunnelSummary,
    OracleBackend,
    OracleCard,
    OracleStatus,
    PerturbationSpec,
    StressSuite,
    TrialEndpoints,
    summarize_scores,
)
from .core import Action, Observation, StepResult, TaskSpec
from .domains import build_electrolyte_line_env, build_electrolyte_registry
from .electrolyte import ElectrolyteReplayEnv, make_fixture_task
from .lab import LabGymEnv, LabRuntime, SkillRegistry
from .planning import PlanningEnv

__all__ = [
    "Action",
    "BenchmarkManifest",
    "DatasetSplit",
    "EndpointEvidence",
    "EndpointName",
    "FunnelSummary",
    "OracleBackend",
    "OracleCard",
    "OracleStatus",
    "PerturbationSpec",
    "StressSuite",
    "TrialEndpoints",
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
    "summarize_scores",
]
