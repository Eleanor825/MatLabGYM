"""MatLabGYM: verifiable environments for materials-science agents."""

from .benchmark import (
    BenchmarkManifest,
    ClaimProfile,
    CohortResult,
    DatasetSplit,
    EndpointEvidence,
    EndpointName,
    EpisodeOutcome,
    FunnelSummary,
    OracleBackend,
    OracleCard,
    OracleStatus,
    PerturbationSpec,
    StressSuite,
    TrialEndpoints,
    TrialOutcome,
    TrialSlot,
    summarize_clustered_scores,
    summarize_scores,
)
from .core import Action, Observation, StepResult, TaskSpec
from .domains import build_electrolyte_line_env, build_electrolyte_registry
from .electrolyte import ElectrolyteReplayEnv, make_fixture_task
from .lab import LabGymEnv, LabRuntime, SkillRegistry
from .planning import PlanningEnv
from .runner import run_cohort, run_trial
from .stress import (
    PairOutcome,
    StressCase,
    operator_attestation,
    run_paired_stress,
    summarize_pairs,
)

__all__ = [
    "Action",
    "BenchmarkManifest",
    "ClaimProfile",
    "CohortResult",
    "DatasetSplit",
    "EndpointEvidence",
    "EndpointName",
    "EpisodeOutcome",
    "FunnelSummary",
    "OracleBackend",
    "OracleCard",
    "OracleStatus",
    "PerturbationSpec",
    "StressSuite",
    "TrialOutcome",
    "TrialSlot",
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
    "PairOutcome",
    "StressCase",
    "run_cohort",
    "run_paired_stress",
    "run_trial",
    "operator_attestation",
    "summarize_pairs",
    "summarize_scores",
    "summarize_clustered_scores",
]
