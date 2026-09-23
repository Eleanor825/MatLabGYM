"""Paired synthetic stress execution with explicit base/perturbed accounting."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import Any, Callable, Dict, Optional, Sequence

from .benchmark import PerturbationSpec, TrialOutcome, TrialSlot, stable_hash
from .core import Action
from .runner import EnvFactory, Policy, ScoreFn, run_trial


@dataclass(frozen=True)
class StressCase:
    pair_id: str
    base_slot: TrialSlot
    perturbed_slot: TrialSlot
    perturbation: PerturbationSpec

    def __post_init__(self) -> None:
        if not self.pair_id.strip():
            raise ValueError("pair_id must be non-empty")
        if self.base_slot.slot_id == self.perturbed_slot.slot_id:
            raise ValueError("base and perturbed slots must differ")
        for field_name in ("task_id", "task_group", "seed", "method_id", "budget_spec"):
            if getattr(self.base_slot, field_name) != getattr(self.perturbed_slot, field_name):
                raise ValueError("paired slots must share %s" % field_name)
        if self.base_slot.benchmark_manifest_hash != self.perturbed_slot.benchmark_manifest_hash:
            raise ValueError("paired slots must share benchmark_manifest_hash")
        if self.base_slot.replicate_id != self.perturbed_slot.replicate_id:
            raise ValueError("paired slots must share replicate_id")
        if self.perturbed_slot.perturbation_id != self.perturbation.perturbation_id:
            raise ValueError("perturbed slot must name the perturbation")
        if self.perturbation.source != "synthetic":
            raise ValueError("this runner only executes explicitly synthetic perturbations")
        if not self.perturbation.implemented or self.perturbation.operator_hash == "unregistered":
            raise ValueError("perturbation requires an implemented operator attestation")

    @property
    def realization_hash(self) -> str:
        return stable_hash(
            {
                "pair_id": self.pair_id,
                "perturbation": self.perturbation.to_dict(),
                "seed": self.base_slot.seed,
            }
        )


@dataclass(frozen=True)
class PairOutcome:
    pair_id: str
    perturbation_id: str
    operator_hash: str
    realization_hash: str
    parameter_hash: str
    base: TrialOutcome
    perturbed: TrialOutcome

    @property
    def score_delta(self) -> float:
        return self.perturbed.score - self.base.score

    @property
    def robustness_delta(self) -> float:
        return self.base.score - self.perturbed.score

    def __post_init__(self) -> None:
        for name in (
            "pair_id",
            "perturbation_id",
            "operator_hash",
            "realization_hash",
            "parameter_hash",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s must be a non-empty string" % name)
        if not self.operator_hash.startswith("sha256:"):
            raise ValueError("operator_hash must be an attestation hash")
        if not self.realization_hash.startswith("sha256:") or not self.parameter_hash.startswith(
            "sha256:"
        ):
            raise ValueError("pair realization hashes must be attestations")
        if self.base.slot.task_id != self.perturbed.slot.task_id:
            raise ValueError("pair task ids must match")
        if self.base.slot.method_id != self.perturbed.slot.method_id:
            raise ValueError("pair methods must match")
        if self.base.slot.benchmark_manifest_hash != self.perturbed.slot.benchmark_manifest_hash:
            raise ValueError("pair manifests must match")
        if self.base.slot.seed != self.perturbed.slot.seed:
            raise ValueError("pair seeds must match")
        if self.base.slot.replicate_id != self.perturbed.slot.replicate_id:
            raise ValueError("pair replicates must match")
        if self.base.slot.budget_spec != self.perturbed.slot.budget_spec:
            raise ValueError("pair budgets must match")
        if self.perturbed.slot.perturbation_id != self.perturbation_id:
            raise ValueError("pair perturbation id does not match slot")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "perturbation_id": self.perturbation_id,
            "operator_hash": self.operator_hash,
            "realization_hash": self.realization_hash,
            "parameter_hash": self.parameter_hash,
            "score_delta": self.score_delta,
            "robustness_delta": self.robustness_delta,
            "base": self.base.to_dict(),
            "perturbed": self.perturbed.to_dict(),
        }


def _operator_for(spec: PerturbationSpec) -> Callable[[int, Action], Sequence[Action]]:
    parameters = dict(spec.parameters)
    family = spec.family

    if family == "invalid_action":
        target_step = int(parameters.get("step", 0))

        def invalid_action(index: int, action: Action) -> Sequence[Action]:
            if index == target_step:
                return (Action("__synthetic_invalid_action__", {}),)
            return (action,)

        return invalid_action
    if family == "duplicate_action":
        target_step = int(parameters.get("step", 0))

        def duplicate_action(index: int, action: Action) -> Sequence[Action]:
            return (action, action) if index == target_step else (action,)

        return duplicate_action
    if family == "time_delay":
        delta = float(parameters.get("minutes", 1.0))

        def time_delay(index: int, action: Action) -> Sequence[Action]:
            if action.name != "advance_time":
                return (action,)
            updated = dict(action.parameters)
            updated["minutes"] = float(updated.get("minutes", 0.0)) + delta
            return (Action(action.name, updated),)

        return time_delay
    raise ValueError("no registered synthetic stress operator: %s" % family)


def operator_attestation(spec: PerturbationSpec) -> str:
    if spec.family not in {"invalid_action", "duplicate_action", "time_delay"}:
        raise ValueError("no registered synthetic stress operator: %s" % spec.family)
    return stable_hash(
        {
            "family": spec.family,
            "version": "v1",
            "implementation": "matlabgym.stress._operator_for",
        }
    )


def summarize_pairs(
    pairs: Sequence[PairOutcome], bootstrap_samples: int = 2000, seed: int = 0
) -> Dict[str, Any]:
    """Aggregate synthetic paired deltas without mixing them with real failures."""
    if not pairs:
        raise ValueError("pairs must not be empty")
    if (
        isinstance(bootstrap_samples, bool)
        or not isinstance(bootstrap_samples, int)
        or bootstrap_samples <= 0
    ):
        raise ValueError("bootstrap_samples must be a positive integer")
    retained = [
        pair
        for pair in pairs
        if pair.base.status == "retained" and pair.perturbed.status == "retained"
    ]
    deltas = [pair.score_delta for pair in pairs]
    conditional_deltas = [pair.score_delta for pair in retained]
    import random

    rng = random.Random(seed)
    bootstrap_source = conditional_deltas or [0.0]
    boot = sorted(
        mean(rng.choice(bootstrap_source) for _ in bootstrap_source)
        for _ in range(bootstrap_samples)
    )
    low = boot[int(0.025 * (len(boot) - 1))]
    high = boot[int(0.975 * (len(boot) - 1))]
    transitions: Dict[str, Dict[str, int]] = {}
    for pair in pairs:
        transitions.setdefault(pair.base.status, {})[pair.perturbed.status] = (
            transitions.setdefault(pair.base.status, {}).get(pair.perturbed.status, 0) + 1
        )
    return {
        "n_pairs": len(pairs),
        "n_assigned": len(pairs),
        "n_retained": len(retained),
        "n_unscorable": len(pairs) - len(retained),
        "conditional_n": len(retained),
        "mean_delta_fixed_denominator": mean(deltas),
        "mean_delta_conditional": mean(conditional_deltas) if conditional_deltas else None,
        "median_delta_conditional": median(conditional_deltas) if conditional_deltas else None,
        "mean_delta": mean(deltas),
        "median_delta": median(deltas),
        "bootstrap_ci95": [low, high],
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": seed,
        "recovery_rate_conditional": (
            sum(pair.perturbed.score >= pair.base.score for pair in retained) / len(retained)
            if retained
            else None
        ),
        "failure_transition_matrix": transitions,
        "source": "synthetic",
    }


def run_paired_stress(
    case: StressCase,
    env_factory: EnvFactory,
    policy: Policy,
    *,
    score_fn: Optional[ScoreFn] = None,
) -> PairOutcome:
    """Run matched base/perturbed episodes with one seed and one budget."""
    if case.perturbation.operator_hash != operator_attestation(case.perturbation):
        raise ValueError("operator hash does not match the registered implementation")
    base = run_trial(case.base_slot, env_factory, policy, score_fn=score_fn)
    perturbed = run_trial(
        case.perturbed_slot,
        env_factory,
        policy,
        score_fn=score_fn,
        action_transform=_operator_for(case.perturbation),
    )
    return PairOutcome(
        pair_id=case.pair_id,
        perturbation_id=case.perturbation.perturbation_id,
        operator_hash=case.perturbation.operator_hash,
        realization_hash=case.realization_hash,
        parameter_hash=stable_hash(dict(case.perturbation.parameters)),
        base=base,
        perturbed=perturbed,
    )
