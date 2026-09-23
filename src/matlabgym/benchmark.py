"""Paper-facing benchmark contracts and deterministic evaluation utilities.

This module deliberately contains metadata and evaluation contracts rather than
pretending that the bundled fixture is a scientific oracle.  A benchmark claim
is admissible only when its oracle card, split, evaluator and stress manifest
are frozen and hashed together.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean, stdev
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


def stable_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return value == value and value not in (float("inf"), float("-inf"))
    except OverflowError:
        return False


class OracleBackend(str, Enum):
    EMPIRICAL_REPLAY = "empirical_replay"
    CALIBRATED_SIMULATOR = "calibrated_simulator"
    SURROGATE = "surrogate"
    REAL_LAB_ADAPTER = "real_lab_adapter"


class OracleStatus(str, Enum):
    EXPLORATORY = "exploratory"
    CALIBRATION_PENDING = "calibration_pending"
    VALIDATED = "validated"


class ClaimProfile(str, Enum):
    EXECUTION_ONLY = "execution_only"
    SCIENTIFIC_BENCHMARK = "scientific_benchmark"
    PHYSICAL_DEPLOYMENT = "physical_deployment"


@dataclass(frozen=True)
class OracleCard:
    """Evidence card required before an oracle can support a scientific claim."""

    oracle_id: str
    backend_type: OracleBackend
    dataset_or_model_version: str
    valid_regime: Mapping[str, Any]
    calibration_split: str
    validation_metrics: Mapping[str, float]
    uncertainty_semantics: str
    known_failure_modes: Tuple[str, ...]
    counterfactual_support: bool
    license: str
    provenance: str
    evaluator_version: str
    status: OracleStatus = OracleStatus.EXPLORATORY

    def __post_init__(self) -> None:
        for name in (
            "oracle_id",
            "dataset_or_model_version",
            "calibration_split",
            "uncertainty_semantics",
            "license",
            "provenance",
            "evaluator_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s must be a non-empty string" % name)
        if not isinstance(self.backend_type, OracleBackend):
            raise ValueError("backend_type must be an OracleBackend")
        if not isinstance(self.status, OracleStatus):
            raise ValueError("status must be an OracleStatus")
        if not isinstance(self.valid_regime, Mapping):
            raise ValueError("valid_regime must be an object")
        try:
            stable_hash(self.valid_regime)
        except (TypeError, ValueError) as exc:
            raise ValueError("valid_regime must be finite JSON-compatible") from exc
        if not isinstance(self.validation_metrics, Mapping):
            raise ValueError("validation_metrics must be an object")
        for name, value in self.validation_metrics.items():
            if not isinstance(name, str) or not is_finite_number(value) or value < 0:
                raise ValueError("validation_metrics must contain finite non-negative numbers")
        if not isinstance(self.known_failure_modes, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.known_failure_modes
        ):
            raise ValueError("known_failure_modes must be a tuple of non-empty strings")
        if not isinstance(self.counterfactual_support, bool):
            raise ValueError("counterfactual_support must be a boolean")
        if self.status is OracleStatus.VALIDATED and not self.validation_metrics:
            raise ValueError("validated oracles require validation_metrics")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "oracle_id": self.oracle_id,
            "backend_type": self.backend_type.value,
            "dataset_or_model_version": self.dataset_or_model_version,
            "valid_regime": dict(self.valid_regime),
            "calibration_split": self.calibration_split,
            "validation_metrics": dict(self.validation_metrics),
            "uncertainty_semantics": self.uncertainty_semantics,
            "known_failure_modes": list(self.known_failure_modes),
            "counterfactual_support": self.counterfactual_support,
            "license": self.license,
            "provenance": self.provenance,
            "evaluator_version": self.evaluator_version,
            "status": self.status.value,
        }

    @property
    def card_hash(self) -> str:
        return stable_hash(self.to_dict())

    def assert_benchmark_ready(self) -> None:
        if self.status is not OracleStatus.VALIDATED:
            raise ValueError(
                "oracle %s is %s and cannot support a scientific benchmark claim"
                % (self.oracle_id, self.status.value)
            )


@dataclass(frozen=True)
class DatasetSplit:
    split_id: str
    grouping_key: str
    train_ids: Tuple[str, ...]
    dev_ids: Tuple[str, ...]
    test_ids: Tuple[str, ...]
    provenance: str

    def __post_init__(self) -> None:
        for name in ("split_id", "grouping_key", "provenance"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s must be a non-empty string" % name)
        raw_groups = {"train": self.train_ids, "dev": self.dev_ids, "test": self.test_ids}
        if any(
            not isinstance(item, str) or not item.strip()
            for values in raw_groups.values()
            for item in values
        ):
            raise ValueError("split ids must be non-empty strings")
        if any(len(values) != len(set(values)) for values in raw_groups.values()):
            raise ValueError("dataset split groups contain duplicate ids")
        sets = {name: set(values) for name, values in raw_groups.items()}
        names = list(sets)
        for left_index, left in enumerate(names):
            for right in names[left_index + 1 :]:
                if sets[left] & sets[right]:
                    raise ValueError("dataset split groups overlap: %s and %s" % (left, right))
        if not sets["test"]:
            raise ValueError("test split must not be empty")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "split_id": self.split_id,
            "grouping_key": self.grouping_key,
            "train_ids": list(self.train_ids),
            "dev_ids": list(self.dev_ids),
            "test_ids": list(self.test_ids),
            "provenance": self.provenance,
        }

    @property
    def split_hash(self) -> str:
        return stable_hash(self.to_dict())


@dataclass(frozen=True)
class PerturbationSpec:
    perturbation_id: str
    family: str
    severity: float
    source: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    paired_base_id: Optional[str] = None
    implemented: bool = False
    operator_hash: str = "unregistered"

    def __post_init__(self) -> None:
        for name in ("perturbation_id", "family", "source"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s must be a non-empty string" % name)
        if not is_finite_number(self.severity) or not 0.0 <= self.severity <= 1.0:
            raise ValueError("severity must be a finite number in [0, 1]")
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be an object")
        stable_hash(self.parameters)
        if self.paired_base_id is not None and not isinstance(self.paired_base_id, str):
            raise ValueError("paired_base_id must be a string or null")
        if not isinstance(self.implemented, bool):
            raise ValueError("implemented must be a boolean")
        if not isinstance(self.operator_hash, str) or not self.operator_hash.strip():
            raise ValueError("operator_hash must be a non-empty string")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "perturbation_id": self.perturbation_id,
            "family": self.family,
            "severity": self.severity,
            "source": self.source,
            "parameters": dict(self.parameters),
            "paired_base_id": self.paired_base_id,
            "implemented": self.implemented,
            "operator_hash": self.operator_hash,
        }


@dataclass(frozen=True)
class StressSuite:
    suite_id: str
    version: str
    perturbations: Tuple[PerturbationSpec, ...]
    combination_policy: str = "single_and_registered_pairs"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.suite_id, str)
            or not isinstance(self.version, str)
            or not self.suite_id.strip()
            or not self.version.strip()
        ):
            raise ValueError("suite_id and version must be non-empty")
        ids = [item.perturbation_id for item in self.perturbations]
        if len(ids) != len(set(ids)):
            raise ValueError("stress perturbation ids must be unique")
        if self.combination_policy not in {"single_only", "single_and_registered_pairs"}:
            raise ValueError("unsupported combination_policy")
        ids = {item.perturbation_id for item in self.perturbations}
        for item in self.perturbations:
            if item.paired_base_id is not None and item.paired_base_id not in ids:
                raise ValueError("paired_base_id is not registered: %s" % item.paired_base_id)

    @property
    def implementation_status(self) -> str:
        return (
            "implemented" if all(item.implemented for item in self.perturbations) else "declarative"
        )

    def assert_implemented(self) -> None:
        if self.implementation_status != "implemented" or any(
            item.operator_hash == "unregistered" for item in self.perturbations
        ):
            raise ValueError("stress suite is declarative or missing operator attestations")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "version": self.version,
            "perturbations": [item.to_dict() for item in self.perturbations],
            "combination_policy": self.combination_policy,
        }

    @property
    def suite_hash(self) -> str:
        return stable_hash(self.to_dict())


class EndpointName(str, Enum):
    PLAN_MATERIALIZED = "plan_materialized"
    DISPATCH_VERIFIED = "dispatch_verified"
    STARTED = "started"
    COMPLETED = "completed"
    SCIENTIFICALLY_VALIDATED = "scientifically_validated"


@dataclass(frozen=True)
class EndpointEvidence:
    endpoint: EndpointName
    present: bool
    evidence_source: str
    artifact_refs: Tuple[str, ...] = ()
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, EndpointName):
            raise ValueError("endpoint must be an EndpointName")
        if not isinstance(self.present, bool):
            raise ValueError("present must be a boolean")
        if not isinstance(self.evidence_source, str) or not self.evidence_source.strip():
            raise ValueError("evidence_source must be a non-empty string")
        if not isinstance(self.artifact_refs, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.artifact_refs
        ):
            raise ValueError("artifact_refs must be a tuple of non-empty strings")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "endpoint": self.endpoint.value,
            "present": self.present,
            "evidence_source": self.evidence_source,
            "artifact_refs": list(self.artifact_refs),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TrialEndpoints:
    trial_id: str
    evidence: Tuple[EndpointEvidence, ...]
    failure_category: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.trial_id, str) or not self.trial_id.strip():
            raise ValueError("trial_id must be a non-empty string")
        endpoints = [item.endpoint for item in self.evidence]
        if len(endpoints) != len(set(endpoints)):
            raise ValueError("trial endpoint evidence must contain one record per endpoint")

    def reached(self, endpoint: EndpointName) -> bool:
        return any(item.endpoint is endpoint and item.present for item in self.evidence)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "evidence": [item.to_dict() for item in self.evidence],
            "failure_category": self.failure_category,
        }


@dataclass(frozen=True)
class TrialSlot:
    """One pre-registered denominator slot in a cohort evaluation."""

    slot_id: str
    benchmark_manifest_hash: str
    task_id: str
    task_group: str
    seed: int
    replicate_id: int
    method_id: str
    perturbation_id: str = "none"
    budget_spec: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "slot_id",
            "benchmark_manifest_hash",
            "task_id",
            "task_group",
            "method_id",
            "perturbation_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s must be a non-empty string" % name)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if (
            isinstance(self.replicate_id, bool)
            or not isinstance(self.replicate_id, int)
            or self.replicate_id < 0
        ):
            raise ValueError("replicate_id must be a non-negative integer")
        if not isinstance(self.budget_spec, Mapping):
            raise ValueError("budget_spec must be an object")
        stable_hash(self.budget_spec)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "benchmark_manifest_hash": self.benchmark_manifest_hash,
            "task_id": self.task_id,
            "task_group": self.task_group,
            "seed": self.seed,
            "replicate_id": self.replicate_id,
            "method_id": self.method_id,
            "perturbation_id": self.perturbation_id,
            "budget_spec": dict(self.budget_spec),
        }


@dataclass(frozen=True)
class EpisodeOutcome:
    """Episode-level evidence; physical/scientific endpoints stay separate."""

    logical_plan_materialized: bool
    logical_dispatch_verified: bool
    logical_completed: bool
    physical_started: bool
    physical_completed: bool
    scientifically_validated: bool
    goal_reached: bool
    failure_categories: Tuple[str, ...]
    total_reward: float
    logical_time_min: float
    total_cost: float
    artifact_refs: Tuple[str, ...]
    physical_evidence_source: Optional[str] = None
    scientific_evidence_source: Optional[str] = None

    def __post_init__(self) -> None:
        for name in (
            "logical_plan_materialized",
            "logical_dispatch_verified",
            "logical_completed",
            "physical_started",
            "physical_completed",
            "scientifically_validated",
            "goal_reached",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError("%s must be a boolean" % name)
        if self.physical_started or self.physical_completed:
            if not self.physical_evidence_source or not self.physical_evidence_source.strip():
                raise ValueError("physical endpoints require authoritative evidence")
        if self.scientifically_validated:
            if not self.scientific_evidence_source or not self.scientific_evidence_source.strip():
                raise ValueError("scientific validation requires evaluator evidence")
        if not isinstance(self.failure_categories, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.failure_categories
        ):
            raise ValueError("failure_categories must be a tuple of strings")
        if not is_finite_number(self.total_reward) or not is_finite_number(self.logical_time_min):
            raise ValueError("reward and logical time must be finite")
        if not is_finite_number(self.total_cost) or self.total_cost < 0:
            raise ValueError("total_cost must be finite and non-negative")
        if not isinstance(self.artifact_refs, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.artifact_refs
        ):
            raise ValueError("artifact_refs must be a tuple of strings")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "logical_plan_materialized": self.logical_plan_materialized,
            "logical_dispatch_verified": self.logical_dispatch_verified,
            "logical_completed": self.logical_completed,
            "physical_started": self.physical_started,
            "physical_completed": self.physical_completed,
            "scientifically_validated": self.scientifically_validated,
            "goal_reached": self.goal_reached,
            "failure_categories": list(self.failure_categories),
            "total_reward": self.total_reward,
            "logical_time_min": self.logical_time_min,
            "total_cost": self.total_cost,
            "artifact_refs": list(self.artifact_refs),
            "physical_evidence_source": self.physical_evidence_source,
            "scientific_evidence_source": self.scientific_evidence_source,
        }


@dataclass(frozen=True)
class TrialOutcome:
    slot: TrialSlot
    status: str
    score: float
    outcome: EpisodeOutcome
    trace: Tuple[Mapping[str, Any], ...]
    attempt_id: str = "attempt-0001"
    parent_attempt_id: Optional[str] = None
    failure_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in {
            "retained",
            "unscorable",
            "runner_failed",
            "infra_failed",
            "scientific_failed",
        }:
            raise ValueError("unsupported trial status: %s" % self.status)
        if not is_finite_number(self.score):
            raise ValueError("trial score must be finite")
        if self.status != "retained" and self.score != 0.0:
            raise ValueError("unscorable trial scores must be zero")
        if not isinstance(self.trace, tuple):
            raise ValueError("trace must be a tuple")
        if not isinstance(self.attempt_id, str) or not self.attempt_id.strip():
            raise ValueError("attempt_id must be a non-empty string")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot": self.slot.to_dict(),
            "status": self.status,
            "score": self.score,
            "outcome": self.outcome.to_dict(),
            "trace": [dict(item) for item in self.trace],
            "attempt_id": self.attempt_id,
            "parent_attempt_id": self.parent_attempt_id,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class CohortResult:
    method_id: str
    n_assigned: int
    n_retained: int
    n_unscorable: int
    outcomes: Tuple[TrialOutcome, ...]
    score_summary: Mapping[str, Any]
    endpoint_summary: Mapping[str, Any]
    status_counts: Mapping[str, int] = field(default_factory=dict)
    conditional_n: int = 0

    def __post_init__(self) -> None:
        if self.n_assigned != len(self.outcomes):
            raise ValueError("n_assigned must equal retained outcome records")
        if self.n_retained + self.n_unscorable != self.n_assigned:
            raise ValueError("cohort counts must partition the fixed denominator")
        if len({item.slot.slot_id for item in self.outcomes}) != self.n_assigned:
            raise ValueError("cohort outcomes must contain one record per slot")
        if any(item.slot.method_id != self.method_id for item in self.outcomes):
            raise ValueError("cohort outcome method does not match method_id")
        if self.conditional_n < 0 or self.conditional_n > self.n_assigned:
            raise ValueError("conditional_n must lie within the fixed denominator")
        if self.conditional_n != self.n_retained:
            raise ValueError("conditional_n must equal the retained outcome count")
        derived_status_counts: Dict[str, int] = {}
        for item in self.outcomes:
            derived_status_counts[item.status] = derived_status_counts.get(item.status, 0) + 1
        if dict(self.status_counts) != derived_status_counts:
            raise ValueError("status_counts must match retained outcome records")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method_id": self.method_id,
            "n_assigned": self.n_assigned,
            "n_retained": self.n_retained,
            "n_unscorable": self.n_unscorable,
            "outcomes": [item.to_dict() for item in self.outcomes],
            "score_summary": dict(self.score_summary),
            "endpoint_summary": dict(self.endpoint_summary),
            "status_counts": dict(self.status_counts),
            "conditional_n": self.conditional_n,
        }


@dataclass(frozen=True)
class FunnelSummary:
    denominator: int
    counts: Mapping[str, int]
    rates: Mapping[str, float]

    @classmethod
    def from_trials(cls, trials: Sequence[TrialEndpoints]) -> "FunnelSummary":
        denominator = len(trials)
        counts = {
            endpoint.value: sum(item.reached(endpoint) for item in trials)
            for endpoint in EndpointName
        }
        rates = {
            key: (value / denominator if denominator else 0.0) for key, value in counts.items()
        }
        return cls(denominator, counts, rates)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "denominator": self.denominator,
            "counts": dict(self.counts),
            "rates": dict(self.rates),
        }


@dataclass(frozen=True)
class BenchmarkManifest:
    benchmark_id: str
    version: str
    task_manifest_hash: str
    oracle_card_hash: str
    evaluator_version: str
    split_hash: str
    seed_schedule: Tuple[int, ...]
    budget_spec: Mapping[str, Any]
    stress_suite_hash: str
    code_version: str
    claim_status: str = ClaimProfile.EXECUTION_ONLY.value

    def __post_init__(self) -> None:
        for name in (
            "benchmark_id",
            "version",
            "task_manifest_hash",
            "oracle_card_hash",
            "evaluator_version",
            "split_hash",
            "stress_suite_hash",
            "code_version",
            "claim_status",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError("%s must be a non-empty string" % name)
        if not self.seed_schedule or not all(
            isinstance(seed, int) and not isinstance(seed, bool) for seed in self.seed_schedule
        ):
            raise ValueError("seed_schedule must contain at least one integer")
        if not isinstance(self.budget_spec, Mapping):
            raise ValueError("budget_spec must be an object")
        stable_hash(self.budget_spec)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "version": self.version,
            "task_manifest_hash": self.task_manifest_hash,
            "oracle_card_hash": self.oracle_card_hash,
            "evaluator_version": self.evaluator_version,
            "split_hash": self.split_hash,
            "seed_schedule": list(self.seed_schedule),
            "budget_spec": dict(self.budget_spec),
            "stress_suite_hash": self.stress_suite_hash,
            "code_version": self.code_version,
            "claim_status": self.claim_status,
        }

    @property
    def manifest_hash(self) -> str:
        return stable_hash(self.to_dict())

    def assert_benchmark_ready(
        self,
        oracle_card: OracleCard,
        dataset_split: DatasetSplit,
        stress_suite: StressSuite,
    ) -> None:
        oracle_card.assert_benchmark_ready()
        if oracle_card.card_hash != self.oracle_card_hash:
            raise ValueError("oracle card hash does not match manifest")
        if dataset_split.split_hash != self.split_hash:
            raise ValueError("dataset split hash does not match manifest")
        if stress_suite.suite_hash != self.stress_suite_hash:
            raise ValueError("stress suite hash does not match manifest")
        stress_suite.assert_implemented()
        if self.claim_status == ClaimProfile.PHYSICAL_DEPLOYMENT.value:
            raise ValueError(
                "physical_deployment admission requires real-lab telemetry and is unsupported"
            )
        if self.claim_status != ClaimProfile.SCIENTIFIC_BENCHMARK.value:
            raise ValueError("manifest is not authorized for a scientific benchmark claim")


def failure_category(failure_code: Optional[str]) -> Optional[str]:
    if failure_code is None:
        return None
    if failure_code in {"INVALID_PARAMETER", "INVALID_ACTION", "INVALID_PLAN"}:
        return "schema_error"
    if failure_code in {"INPUT_NOT_FOUND", "INPUT_KIND_MISMATCH", "INPUT_STATE_MISMATCH"}:
        return "precondition_error"
    if failure_code in {"RESOURCE_BUSY", "ARTIFACT_BUSY"}:
        return "resource_conflict"
    if failure_code in {"ARTIFACT_CONSUMED"}:
        return "state_continuity_error"
    if failure_code in {"BUDGET_EXCEEDED"}:
        return "budget_exhausted"
    if failure_code in {"UNKNOWN_OPERATION", "UNKNOWN_SKILL"}:
        return "dispatch_error"
    return "runtime_failure"


def summarize_scores(
    scores: Sequence[float], bootstrap_samples: int = 2000, seed: int = 0
) -> Dict[str, Any]:
    """Return mean/std and a deterministic percentile bootstrap interval."""
    if not scores:
        raise ValueError("scores must not be empty")
    if (
        isinstance(bootstrap_samples, bool)
        or not isinstance(bootstrap_samples, int)
        or bootstrap_samples <= 0
    ):
        raise ValueError("bootstrap_samples must be a positive integer")
    if any(not is_finite_number(score) for score in scores):
        raise ValueError("scores must be finite")
    rng = random.Random(seed)
    values = [float(score) for score in scores]
    boot = [mean(rng.choice(values) for _ in values) for _ in range(bootstrap_samples)]
    boot.sort()
    low = boot[int(0.025 * (len(boot) - 1))]
    high = boot[int(0.975 * (len(boot) - 1))]
    return {
        "n": len(values),
        "mean": mean(values),
        "std": stdev(values) if len(values) > 1 else 0.0,
        "bootstrap_ci95": [low, high],
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": seed,
    }


def summarize_clustered_scores(
    records: Sequence[Mapping[str, Any]],
    *,
    cluster_key: str = "task_group",
    score_key: str = "score",
    bootstrap_samples: int = 2000,
    seed: int = 0,
) -> Dict[str, Any]:
    """Summarize fixed-denominator scores with cluster bootstrap.

    Repeated seeds/replicates within one task group are resampled as a unit,
    matching the dependency structure expected in benchmark reporting.
    """
    if not records:
        raise ValueError("records must not be empty")
    if (
        isinstance(bootstrap_samples, bool)
        or not isinstance(bootstrap_samples, int)
        or bootstrap_samples <= 0
    ):
        raise ValueError("bootstrap_samples must be a positive integer")
    grouped: Dict[str, list[float]] = {}
    for record in records:
        cluster = record.get(cluster_key)
        score = record.get(score_key)
        if not isinstance(cluster, str) or not cluster.strip() or not is_finite_number(score):
            raise ValueError("records must contain a string cluster and finite score")
        grouped.setdefault(cluster, []).append(float(score))
    clusters = tuple(sorted(grouped))
    cluster_means = [mean(grouped[key]) for key in clusters]
    rng = random.Random(seed)
    boot = [
        mean(rng.choice(cluster_means) for _ in cluster_means) for _ in range(bootstrap_samples)
    ]
    boot.sort()
    low = boot[int(0.025 * (len(boot) - 1))]
    high = boot[int(0.975 * (len(boot) - 1))]
    return {
        "n_assigned": len(records),
        "n_clusters": len(clusters),
        "cluster_key": cluster_key,
        "cluster_means": dict(zip(clusters, cluster_means)),
        "mean": mean(cluster_means),
        "bootstrap_ci95": [low, high],
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": seed,
    }
