import unittest
from dataclasses import replace
from types import SimpleNamespace

from matlabgym import (
    TrialSlot,
    build_electrolyte_line_env,
    run_cohort,
    run_paired_stress,
    run_trial,
)
from matlabgym.benchmark import EpisodeOutcome, PerturbationSpec
from matlabgym.core import Action
from matlabgym.stress import StressCase, operator_attestation, summarize_pairs


def make_slot():
    env = build_electrolyte_line_env()
    _, info = env.reset(seed=1)
    return TrialSlot(
        "base",
        info["manifest_hash"],
        env.task.task_id,
        "group",
        1,
        0,
        "method",
        budget_spec={"max_steps": 40, "max_time_min": 2000.0, "budget_money": 500.0},
    )


class HookEnv:
    def __init__(self, slot):
        self.slot = slot
        self.task = SimpleNamespace(task_id=slot.task_id, max_steps=999)
        self.budget_spec = {"max_steps": 2}
        self.terminated = False
        self.truncated = False
        self.actions = []

    def reset(self, seed):
        return None, {"manifest_hash": self.slot.benchmark_manifest_hash}

    def observe(self):
        return None

    def step(self, action):
        self.actions.append(action)
        self.terminated = len(self.actions) == 2

    def trace(self):
        return []

    def episode_outcome(self):
        success = [action.name for action in self.actions] == ["first", "second"]
        return EpisodeOutcome(
            False, False, success, False, False, False, success, (), 0.0, 0.0, 0.0, ()
        )


def stateful_factory(slot):
    actions = iter([Action("first", {}), Action("second", {})])
    return lambda _: next(actions, None)


def make_case(slot):
    spec = PerturbationSpec(
        "delay", "time_delay", 1.0, "synthetic", {"minutes": 1}, slot.slot_id, True, "placeholder"
    )
    spec = replace(spec, operator_hash=operator_attestation(spec))
    return StressCase(
        "pair", slot, replace(slot, slot_id="perturbed", perturbation_id="delay"), spec
    )


class RunnerContractTests(unittest.TestCase):
    def test_factory_isolates_trials_and_hook_has_no_runtime_dependency(self):
        slot = make_slot()
        slot = replace(slot, budget_spec={"max_steps": 2})
        created = []

        def factory(assigned):
            created.append(assigned.slot_id)
            return stateful_factory(assigned)

        cohort = run_cohort(
            [slot, replace(slot, slot_id="second")],
            HookEnv,
            policy_factory=factory,
            bootstrap_samples=10,
        )
        self.assertTrue([outcome.score for outcome in cohort.outcomes] == [1, 1])
        self.assertTrue(created == ["base", "second"])
        pair = run_paired_stress(make_case(slot), HookEnv, policy_factory=factory)
        self.assertTrue(pair.base.score == pair.perturbed.score == 1)
        self.assertTrue(created == ["base", "second", "base", "perturbed"])

    def test_missing_budget_fields_allowed(self):
        slot = make_slot()
        outcome = run_trial(replace(slot, budget_spec={}), HookEnv, policy_factory=stateful_factory)
        self.assertTrue(outcome.status == "retained")

    def test_policy_argument_conflicts_are_clear(self):
        slot = make_slot()
        for runner, subject in [
            (run_trial, slot),
            (run_cohort, [slot]),
            (run_paired_stress, make_case(slot)),
        ]:
            with self.assertRaisesRegex(ValueError, "exactly one"):
                runner(subject, HookEnv)
            with self.assertRaisesRegex(ValueError, "exactly one"):
                runner(subject, HookEnv, lambda _: None, policy_factory=stateful_factory)

    def test_factory_failure_is_runner_failure(self):
        slot = make_slot()

        def factory(_):
            raise RuntimeError("factory failed")

        result = run_trial(replace(slot, budget_spec={}), HookEnv, policy_factory=factory)
        self.assertTrue(result.status == "runner_failed")
        self.assertTrue("factory failed" in result.failure_reason)

    def test_stress_ci_distinguishes_fixed_and_conditional(self):
        slot = make_slot()
        slot = replace(slot, budget_spec={})
        pair = run_paired_stress(make_case(slot), HookEnv, policy_factory=stateful_factory)
        failed_pair = replace(
            pair,
            pair_id="failed-pair",
            perturbed=replace(pair.perturbed, status="runner_failed", score=0),
        )
        summary = summarize_pairs([pair, failed_pair], bootstrap_samples=200)
        self.assertTrue(summary["bootstrap_ci95_estimand"] == "mean_delta_conditional")
        self.assertTrue(
            summary["bootstrap_ci95"] == summary["bootstrap_ci95_conditional"] == [0, 0]
        )
        self.assertTrue(summary["bootstrap_ci95_fixed_denominator"] == [-1, 0])
        self.assertTrue(summary["mean_delta_fixed_denominator"] == -0.5)
        no_retained = summarize_pairs([failed_pair], bootstrap_samples=20)
        self.assertTrue(no_retained["bootstrap_ci95"] is None)
        self.assertTrue(no_retained["bootstrap_ci95_fixed_denominator"] == [-1, -1])

    def test_slot_mismatch_retained_in_denominator(self):
        slot = make_slot()
        for changes, reason in [
            ({"task_id": "wrong"}, "task_id"),
            ({"budget_spec": {"max_steps": 39}}, "max_steps"),
            ({"budget_spec": {"max_time_min": 1999}}, "max_time_min"),
            ({"budget_spec": {"budget_money": 499}}, "budget_money"),
            ({"budget_spec": {"unknown": 0}}, "unknown"),
        ]:
            with self.subTest(changes=changes):
                result = run_cohort(
                    [replace(slot, **changes)],
                    lambda _: build_electrolyte_line_env(),
                    lambda _: None,
                    bootstrap_samples=10,
                )
                self.assertEqual(result.n_assigned, 1)
                self.assertEqual(result.status_counts, {"runner_failed": 1})
                self.assertEqual(result.outcomes[0].score, 0)
                self.assertIn(reason, result.outcomes[0].failure_reason)
