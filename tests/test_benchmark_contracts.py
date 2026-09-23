import json
import unittest

from matlabgym import (
    BenchmarkManifest,
    DatasetSplit,
    OracleBackend,
    OracleCard,
    OracleStatus,
    PerturbationSpec,
    StressSuite,
    summarize_scores,
)
from matlabgym.core import Action
from matlabgym.domains import build_electrolyte_line_env
from matlabgym.electrolyte import CSVReplayOracle, ElectrolyteReplayEnv
from matlabgym.replay import verify_trace


class BenchmarkContractTests(unittest.TestCase):
    def valid_card(self, status=OracleStatus.VALIDATED):
        return OracleCard(
            oracle_id="fixture-replay",
            backend_type=OracleBackend.EMPIRICAL_REPLAY,
            dataset_or_model_version="fixture-v1",
            valid_regime={"temperature_c": [30]},
            calibration_split="heldout-formulations-v1",
            validation_metrics={"repeatability_rmse": 0.1},
            uncertainty_semantics="reported measurement uncertainty",
            known_failure_modes=("missing_action",),
            counterfactual_support=False,
            license="internal-test-data",
            provenance="tests/test_benchmark_contracts.py",
            evaluator_version="evaluator-v1",
            status=status,
        )

    def test_scientific_manifest_is_fail_closed_until_stress_operators_exist(self):
        card = self.valid_card()
        split = DatasetSplit(
            "split-v1", "campaign_id", ("train-a",), ("dev-a",), ("test-a",), "test"
        )
        suite = StressSuite(
            "suite-v1",
            "1.0",
            (
                PerturbationSpec(
                    "base",
                    "none",
                    0.0,
                    "synthetic",
                    implemented=True,
                ),
                PerturbationSpec(
                    "missing-observation",
                    "observation_missingness",
                    0.4,
                    "synthetic",
                    {"probability": 0.1},
                    paired_base_id="base",
                    implemented=False,
                ),
            ),
        )
        manifest = BenchmarkManifest(
            "matlabgym-v0",
            "0.2",
            "task-hash",
            card.card_hash,
            card.evaluator_version,
            split.split_hash,
            (0, 1, 2),
            {"max_steps": 10},
            suite.suite_hash,
            "test-revision",
            claim_status="scientific_benchmark",
        )
        with self.assertRaises(ValueError):
            manifest.assert_benchmark_ready(card, split, suite)

    def test_score_bootstrap_and_manifest_hash_are_deterministic(self):
        first = summarize_scores([1.0, 2.0, 3.0], bootstrap_samples=100, seed=9)
        second = summarize_scores([1.0, 2.0, 3.0], bootstrap_samples=100, seed=9)
        self.assertEqual(first, second)
        with self.assertRaises(ValueError):
            summarize_scores([1.0], bootstrap_samples=0)

    def test_replay_verifier_checks_full_episode(self):
        env = build_electrolyte_line_env()
        env.reset(seed=71)
        env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "replay-mix",
                    "parameters": {
                        "recipe": {"components": [{"material": "EC", "fraction": 1.0}]},
                        "batch_size_ml": 10.0,
                    },
                },
            )
        )
        env.step(Action("advance_time", {"minutes": 30, "request_id": "replay-finish"}))
        verification = verify_trace(build_electrolyte_line_env, env.trace(), seed=71)
        self.assertTrue(verification.ok, verification.to_dict())
        self.assertEqual(verification.checked_steps, 2)

        incomplete = list(env.trace())
        del incomplete[0]["manifest_hash"]
        rejected = verify_trace(build_electrolyte_line_env, incomplete, seed=71)
        self.assertFalse(rejected.ok)
        self.assertIn("missing trace fields", rejected.reason)

    def test_endpoint_funnel_aggregates_all_steps_and_does_not_claim_physical_start(self):
        env = build_electrolyte_line_env()
        env.reset(seed=72)
        env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "funnel-mix",
                    "parameters": {
                        "recipe": {"components": [{"material": "EC", "fraction": 1.0}]},
                        "batch_size_ml": 10.0,
                    },
                },
            )
        )
        env.step(Action("advance_time", {"minutes": 30, "request_id": "funnel-finish"}))
        funnel = env.endpoint_funnel()
        self.assertEqual(funnel["denominator"], 1)
        self.assertEqual(funnel["counts"]["dispatch_verified"], 1)
        self.assertEqual(funnel["counts"]["completed"], 1)
        self.assertEqual(funnel["counts"]["started"], 0)
        self.assertEqual(funnel["counts"]["scientifically_validated"], 0)

    def test_sparse_replay_has_explicit_support_and_no_nan(self):
        oracle = CSVReplayOracle(
            [
                {"formulation_id": "A", "temperature_c": "30", "conductivity_ms_cm": "1.0"},
                {"formulation_id": "B", "temperature_c": "20", "conductivity_ms_cm": "2.0"},
            ]
        )
        payload = oracle.measure("A", 30).to_dict()
        json.dumps(payload, allow_nan=False)
        from matlabgym.core import TaskSpec

        task = TaskSpec("sparse", "find", budget=1, max_steps=1, required_target=0.0)
        env = ElectrolyteReplayEnv(task, oracle, temperature_c=30)
        self.assertEqual(env.observe().public_state["support_size"], 1)
        self.assertEqual(len(env.available_actions()), 1)
        evaluation = env.evaluate()
        self.assertEqual(evaluation["support_size"], 1)

    def test_duplicate_replay_rows_are_not_silently_overwritten(self):
        rows = [
            {"formulation_id": "A", "temperature_c": "30", "conductivity_ms_cm": "1.0"},
            {"formulation_id": "A", "temperature_c": "30", "conductivity_ms_cm": "1.1"},
        ]
        with self.assertRaises(ValueError):
            CSVReplayOracle(rows)
        oracle = CSVReplayOracle(rows, duplicate_policy="first")
        self.assertEqual(len(oracle.replicates("A", 30)), 2)


if __name__ == "__main__":
    unittest.main()
