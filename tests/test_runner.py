import unittest

from matlabgym import (
    StressCase,
    TrialSlot,
    build_electrolyte_line_env,
    run_cohort,
    run_paired_stress,
    run_trial,
)
from matlabgym.benchmark import PerturbationSpec, stable_hash
from matlabgym.core import Action
from matlabgym.stress import operator_attestation, summarize_pairs


def make_env():
    return build_electrolyte_line_env()


def skill_policy(observation):
    if observation.step == 0:
        return Action(
            "start_skill",
            {
                "skill_id": "run_electrolyte_cell_line",
                "request_id": "runner-skill",
                "parameters_by_step": {
                    "mix": {
                        "recipe": {"components": [{"material": "EC", "fraction": 1.0}]},
                        "batch_size_ml": 10.0,
                    }
                },
            },
        )
    if observation.step == 1:
        return Action("advance_time", {"minutes": 905, "request_id": "runner-wait"})
    return None


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = make_env()
        _, info = env.reset(seed=0)
        cls.manifest_hash = info["manifest_hash"]

    def slot(self, slot_id, *, seed=1, perturbation_id="none", budget=None):
        return TrialSlot(
            slot_id=slot_id,
            benchmark_manifest_hash=self.manifest_hash,
            task_id="electrolyte.line.complete.v1",
            task_group="fixture-group",
            seed=seed,
            replicate_id=0,
            method_id="scripted-skill",
            perturbation_id=perturbation_id,
            budget_spec=budget or {"max_steps": 40, "budget_money": 500.0},
        )

    def test_run_trial_retains_successful_slot(self):
        result = run_trial(self.slot("slot-1"), lambda slot: make_env(), skill_policy)
        self.assertEqual(result.status, "retained")
        self.assertEqual(result.score, 1.0)
        self.assertTrue(result.outcome.logical_completed)
        self.assertFalse(result.outcome.physical_completed)

    def test_cohort_has_fixed_denominator_and_cluster_summary(self):
        slots = [self.slot("slot-%d" % index, seed=index) for index in range(3)]
        result = run_cohort(slots, lambda slot: make_env(), skill_policy, bootstrap_samples=100)
        self.assertEqual(result.n_assigned, 3)
        self.assertEqual(result.n_retained, 3)
        self.assertEqual(result.n_unscorable, 0)
        self.assertEqual(result.conditional_n, 3)
        self.assertEqual(result.status_counts, {"retained": 3})
        self.assertEqual(result.score_summary["n_assigned"], 3)

    def test_unscorable_and_runner_failure_are_retained_as_zero(self):
        def no_action(_observation):
            return None

        unscorable = run_cohort(
            [self.slot("unscorable")], lambda slot: make_env(), no_action, bootstrap_samples=20
        )
        self.assertEqual(unscorable.n_assigned, 1)
        self.assertEqual(unscorable.n_unscorable, 1)
        self.assertEqual(unscorable.outcomes[0].score, 0.0)

        failed = run_cohort(
            [self.slot("failed")],
            lambda slot: (_ for _ in ()).throw(RuntimeError("synthetic runner failure")),
            skill_policy,
            bootstrap_samples=20,
        )
        self.assertEqual(failed.status_counts, {"runner_failed": 1})
        self.assertEqual(failed.outcomes[0].score, 0.0)

    def test_cohort_rejects_mixed_manifest_or_budget(self):
        mixed_manifest = TrialSlot(
            "mixed-manifest",
            "sha256:other",
            "electrolyte.line.complete.v1",
            "fixture-group",
            1,
            0,
            "scripted-skill",
            budget_spec={"max_steps": 40, "budget_money": 500.0},
        )
        with self.assertRaises(ValueError):
            run_cohort(
                [self.slot("base"), mixed_manifest],
                lambda slot: make_env(),
                skill_policy,
                bootstrap_samples=20,
            )
        with self.assertRaises(ValueError):
            run_cohort(
                [self.slot("base"), self.slot("other", budget={"max_steps": 1})],
                lambda slot: make_env(),
                skill_policy,
                bootstrap_samples=20,
            )

    def test_paired_synthetic_stress_keeps_seed_and_budget(self):
        perturbation = PerturbationSpec(
            perturbation_id="invalid-first-action",
            family="invalid_action",
            severity=1.0,
            source="synthetic",
            parameters={"step": 0},
            paired_base_id="base",
            implemented=True,
            operator_hash=stable_hash(
                {
                    "family": "invalid_action",
                    "version": "v1",
                    "implementation": "matlabgym.stress._operator_for",
                }
            ),
        )
        case = StressCase(
            "pair-1",
            self.slot("base"),
            self.slot("perturbed", perturbation_id=perturbation.perturbation_id),
            perturbation,
        )
        pair = run_paired_stress(case, lambda slot: make_env(), skill_policy)
        self.assertEqual(pair.base.score, 1.0)
        self.assertEqual(pair.perturbed.score, 0.0)
        self.assertEqual(pair.perturbation_id, perturbation.perturbation_id)
        self.assertTrue(pair.realization_hash.startswith("sha256:"))
        self.assertEqual(pair.parameter_hash, stable_hash(dict(perturbation.parameters)))
        summary = summarize_pairs([pair], bootstrap_samples=20)
        self.assertEqual(summary["n_assigned"], 1)
        self.assertEqual(summary["source"], "synthetic")

    def test_paired_stress_rejects_manifest_or_replicate_mismatch(self):
        perturbation = PerturbationSpec(
            perturbation_id="invalid-mismatch",
            family="invalid_action",
            severity=1.0,
            source="synthetic",
            parameters={"step": 0},
            paired_base_id="base",
            implemented=True,
            operator_hash=operator_attestation(
                PerturbationSpec(
                    "invalid-mismatch",
                    "invalid_action",
                    1.0,
                    "synthetic",
                    {"step": 0},
                    "base",
                    True,
                    "placeholder",
                )
            ),
        )
        mismatched = TrialSlot(
            "mismatched",
            "sha256:other",
            "electrolyte.line.complete.v1",
            "fixture-group",
            1,
            9,
            "scripted-skill",
            perturbation_id=perturbation.perturbation_id,
            budget_spec={"max_steps": 40, "budget_money": 500.0},
        )
        with self.assertRaises(ValueError):
            StressCase("bad-pair", self.slot("base"), mismatched, perturbation)


if __name__ == "__main__":
    unittest.main()
