"""Fixed-denominator cohort execution for reproducible agent evaluation."""

from __future__ import annotations

import copy
from typing import Any, Callable, List, Mapping, Optional, Sequence

from .benchmark import (
    CohortResult,
    EpisodeOutcome,
    TrialOutcome,
    TrialSlot,
    summarize_clustered_scores,
)
from .core import Action, Observation

Policy = Callable[[Observation], Optional[Action]]
ScoreFn = Callable[[EpisodeOutcome], float]
EnvFactory = Callable[[TrialSlot], Any]
PolicyFactory = Callable[[TrialSlot], Policy]


def _episode_outcome(env: Any, trace: Sequence[Mapping[str, Any]]) -> EpisodeOutcome:
    outcome = env.episode_outcome()
    if not isinstance(outcome, EpisodeOutcome):
        raise TypeError("environment episode_outcome() must return EpisodeOutcome")
    return outcome


def _validate_policy_source(
    policy: Optional[Policy], policy_factory: Optional[PolicyFactory]
) -> None:
    if (policy is None) == (policy_factory is None):
        raise ValueError("provide exactly one of policy or policy_factory")
    if not callable(policy if policy_factory is None else policy_factory):
        raise TypeError("policy or policy_factory must be callable")


def _validate_slot_environment(slot: TrialSlot, env: Any) -> None:
    if slot.task_id != env.task.task_id:
        raise ValueError("slot task_id does not match environment")
    budget = env.budget_spec
    if not isinstance(budget, Mapping):
        raise TypeError("environment budget_spec must be a mapping")
    for name, value in slot.budget_spec.items():
        if name not in budget:
            raise ValueError("unknown slot budget field: %s" % name)
        if value != budget[name] or isinstance(value, bool) != isinstance(budget[name], bool):
            raise ValueError("slot budget field %s does not match environment" % name)


def run_trial(
    slot: TrialSlot,
    env_factory: EnvFactory,
    policy: Optional[Policy] = None,
    *,
    policy_factory: Optional[PolicyFactory] = None,
    score_fn: Optional[ScoreFn] = None,
    action_transform: Optional[Callable[[int, Action], Sequence[Action]]] = None,
) -> TrialOutcome:
    """Execute a slot, retaining failures; ``policy_factory(slot)`` creates its policy.

    Direct ``policy`` remains supported for stateless callables. Stateful policies
    should use the factory so each trial receives an independent instance.
    """
    _validate_policy_source(policy, policy_factory)
    status = "retained"
    failure_reason = None
    trace: Sequence[Mapping[str, Any]] = ()
    try:
        env = env_factory(slot)
        _, reset_info = env.reset(seed=slot.seed)
        if reset_info.get("manifest_hash") != slot.benchmark_manifest_hash:
            raise ValueError("slot manifest hash does not match environment")
        _validate_slot_environment(slot, env)
        trial_policy = policy_factory(slot) if policy_factory is not None else policy
        if not callable(trial_policy):
            raise TypeError("policy_factory must return a callable policy")
        action_index = 0
        while not env.terminated and not env.truncated:
            action = trial_policy(env.observe())
            if action is None:
                status = "unscorable"
                failure_reason = "policy returned no action before termination"
                break
            actions = (
                tuple(action_transform(action_index, action))
                if action_transform is not None
                else (action,)
            )
            if not actions:
                status = "unscorable"
                failure_reason = "action transform returned no actions"
                break
            for transformed in actions:
                if env.terminated or env.truncated:
                    break
                env.step(transformed)
                action_index += 1
        trace = tuple(copy.deepcopy(env.trace()))
        outcome = _episode_outcome(env, trace)
        score = float(score_fn(outcome) if score_fn is not None else outcome.goal_reached)
        if status != "retained":
            score = 0.0
    except Exception as exc:  # Retain infrastructure failures in the denominator.
        status = "runner_failed"
        failure_reason = "%s: %s" % (type(exc).__name__, exc)
        outcome = EpisodeOutcome(
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            ("runner_failure",),
            0.0,
            0.0,
            0.0,
            (),
        )
        score = 0.0
    return TrialOutcome(
        slot=slot,
        status=status,
        score=score,
        outcome=outcome,
        trace=tuple(trace),
        failure_reason=failure_reason,
    )


def run_cohort(
    slots: Sequence[TrialSlot],
    env_factory: EnvFactory,
    policy: Optional[Policy] = None,
    *,
    policy_factory: Optional[PolicyFactory] = None,
    score_fn: Optional[ScoreFn] = None,
    evaluator_version: Optional[str] = None,
    bootstrap_samples: int = 2000,
    bootstrap_seed: int = 0,
) -> CohortResult:
    """Run every pre-registered slot and retain failures in the denominator.

    The runner is intentionally policy/evaluator agnostic.  It reports logical
    execution evidence from the environment, while an independent ``score_fn``
    may add a scientific evaluator once one is registered.
    """
    _validate_policy_source(policy, policy_factory)
    if score_fn is not None and not evaluator_version:
        raise ValueError("custom score_fn requires an evaluator_version")
    if not slots:
        raise ValueError("slots must not be empty")
    slot_ids = [slot.slot_id for slot in slots]
    if len(slot_ids) != len(set(slot_ids)):
        raise ValueError("slot_id must be unique in a cohort")
    method_ids = {slot.method_id for slot in slots}
    if len(method_ids) != 1:
        raise ValueError("run_cohort accepts one method_id per invocation")
    manifest_hashes = {slot.benchmark_manifest_hash for slot in slots}
    if len(manifest_hashes) != 1:
        raise ValueError("all slots must use one benchmark manifest hash")
    budget_hashes = {repr(sorted(slot.budget_spec.items())) for slot in slots}
    if len(budget_hashes) != 1:
        raise ValueError("all slots must use one budget specification")
    scorer = score_fn or (lambda outcome: 1.0 if outcome.goal_reached else 0.0)
    outcomes: List[TrialOutcome] = []
    for slot in slots:
        outcomes.append(
            run_trial(slot, env_factory, policy, policy_factory=policy_factory, score_fn=scorer)
        )

    score_records = [
        {
            "task_group": item.slot.task_group,
            "score": item.score,
            "status": item.status,
        }
        for item in outcomes
    ]
    endpoint_names = (
        "logical_plan_materialized",
        "logical_dispatch_verified",
        "logical_completed",
        "physical_started",
        "physical_completed",
        "scientifically_validated",
    )
    endpoint_counts = {
        name: sum(bool(getattr(item.outcome, name)) for item in outcomes) for name in endpoint_names
    }
    n_assigned = len(slots)
    endpoint_summary = {
        "n_assigned": n_assigned,
        "counts": endpoint_counts,
        "rates": {name: count / n_assigned for name, count in endpoint_counts.items()},
    }
    return CohortResult(
        method_id=next(iter(method_ids)),
        n_assigned=n_assigned,
        n_retained=sum(item.status == "retained" for item in outcomes),
        n_unscorable=sum(item.status != "retained" for item in outcomes),
        outcomes=tuple(outcomes),
        score_summary=summarize_clustered_scores(
            score_records,
            bootstrap_samples=bootstrap_samples,
            seed=bootstrap_seed,
        ),
        endpoint_summary=endpoint_summary,
        status_counts={
            status: sum(item.status == status for item in outcomes)
            for status in sorted({item.status for item in outcomes})
        },
        conditional_n=sum(item.status == "retained" for item in outcomes),
    )
