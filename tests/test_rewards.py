import copy
import unittest

from matlabgym import Action, ReplayRewardSpec, TaskSpec, TrialSlot, run_trial
from matlabgym.domains import build_electrolyte_line_env
from matlabgym.electrolyte import CSVReplayOracle, ElectrolyteReplayEnv
from matlabgym.lab import RewardSpec
from matlabgym.replay import endpoint_record_from_trace, verify_trace


def make_env(reward=None, budget=3, target=9.0, max_steps=8):
    rows = [
        {"formulation_id": name, "temperature_c": "30", "conductivity_ms_cm": str(value)}
        for name, value in (("A", 4), ("B", 3), ("C", 9), ("D", 7))
    ]
    return ElectrolyteReplayEnv(
        TaskSpec("reward-test", "find target", max_steps, budget, target),
        CSVReplayOracle(rows), reward=reward,
    )


def measure(name):
    return Action("measure_conductivity", {"formulation_id": name, "temperature_c": 30})


class RewardTests(unittest.TestCase):
    def test_reward_changes_return_but_not_science_or_dynamics(self):
        sparse = make_env(ReplayRewardSpec.sparse_goal())
        dense = make_env(ReplayRewardSpec.cost_aware(scale=10, measurement_cost=0.1))
        sparse_return = dense_return = 0.0
        for name in ("A", "B", "C"):
            a, b = sparse.step(measure(name)), dense.step(measure(name))
            sparse_return += a.reward
            dense_return += b.reward
            self.assertEqual(a.observation.public_state, b.observation.public_state)
            self.assertEqual((a.terminated, a.truncated), (b.terminated, b.truncated))
            self.assertAlmostEqual(b.reward, sum(b.info["reward_components"].values()))
        self.assertEqual(sparse_return, 1.0)
        self.assertAlmostEqual(dense_return, 1.6)
        self.assertEqual(sparse.evaluate(), dense.evaluate())
        self.assertNotEqual(sparse.manifest.manifest_hash, dense.manifest.manifest_hash)

    def test_improvement_telescopes_and_duplicate_cannot_farm_reward(self):
        env = make_env(ReplayRewardSpec.improvement(scale=10))
        first = env.step(measure("A"))
        duplicate = env.step(measure("A"))
        worse = env.step(measure("B"))
        last = env.step(measure("C"))
        self.assertEqual(duplicate.reward, -1.0)
        self.assertEqual(duplicate.info["query_cost"], 0)
        self.assertEqual(worse.info["reward_components"]["improvement"], 0)
        self.assertAlmostEqual(sum(
            e.info["reward_components"]["improvement"] for e in (first, duplicate, worse, last)
        ), 0.9)
        self.assertEqual(env.evaluate()["experiments_to_target"], 3)
        self.assertEqual(env.evaluate()["actions_to_target"], 4)

    def test_budget_truncates_and_support_exhaustion_terminates(self):
        env = make_env(budget=1, target=100)
        result = env.step(measure("A"))
        self.assertFalse(result.terminated)
        self.assertTrue(result.truncated)
        env = make_env(budget=5, target=100)
        for name in ("A", "B", "C", "D"):
            result = env.step(measure(name))
        self.assertTrue(result.terminated)
        self.assertFalse(result.truncated)
        self.assertFalse(result.info["success"])

    def test_support_validation_and_caller_mutation_isolation(self):
        env = make_env()
        result = env.step(measure("A"))
        result.info["measurement"]["conductivity_ms_cm"] = 1e6
        result.observation.last_outcome["measurement"]["conductivity_ms_cm"] = 1e6
        result.observation.public_state["measurements"][0]["conductivity_ms_cm"] = 1e6
        self.assertEqual(env.evaluate()["best_found_ms_cm"], 4)
        self.assertEqual(env.trace()[0]["info"]["measurement"]["conductivity_ms_cm"], 4)
        bad = env.step(Action("measure_conductivity", {
            "formulation_id": "A", "temperature_c": 30.9,
        }))
        self.assertFalse(bad.info["valid"])
        self.assertEqual(env.budget_remaining, 2)
        obs = env.observe().to_dict()
        self.assertNotIn("oracle_optimum_ms_cm", obs["public_state"])
        self.assertEqual(len(obs["public_state"]["measurements"]), 1)

    def test_reward_and_data_snapshots_are_bound_to_manifest(self):
        env = make_env()
        env.reward_spec = ReplayRewardSpec.sparse_goal()
        with self.assertRaises(ValueError):
            env.step(measure("A"))
        self.assertEqual(env.step_count, 0)
        env = make_env()
        manifest_hash = env.manifest.manifest_hash
        env.oracle._rows.clear()
        env.step(measure("A"))
        self.assertEqual(env.manifest.manifest_hash, manifest_hash)
        self.assertEqual(env.evaluate()["best_found_ms_cm"], 4)

    def test_reward_configuration_validation(self):
        for params in ({"scale": 0}, {"scale": True}, {"goal_bonus": float("nan")},
                       {"measurement_cost": -1}, {"baseline": float("inf")}, {"version": ""}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                ReplayRewardSpec(**params)
        with self.assertRaises(ValueError):
            make_env(ReplayRewardSpec(scale=5e-324))
        reward = ReplayRewardSpec.sparse_goal(baseline=-1e308).components(
            valid=True, previous_best=None, current_best=1e308, goal_reached=False
        )
        self.assertEqual(sum(reward.values()), 0)

    def test_runner_and_full_trace_verifier_accept_replay_environment(self):
        env = make_env()
        slot = TrialSlot("slot", env.manifest.manifest_hash, env.task.task_id, "group", 3, 0,
                         "fixed", budget_spec=env.budget_spec)
        result = run_trial(slot, lambda _: make_env(), lambda obs: measure(
            ("A", "B", "C")[obs.step]
        ))
        self.assertEqual(result.status, "retained", result.failure_reason)
        self.assertEqual(result.score, 1)
        self.assertEqual(result.outcome.total_cost, 3)
        self.assertFalse(result.outcome.scientifically_validated)
        self.assertTrue(verify_trace(make_env, result.trace, seed=3).ok)
        record = endpoint_record_from_trace(result.trace[0])
        endpoints = {e.endpoint.value: e.present for e in record.evidence}
        self.assertFalse(endpoints["plan_materialized"])
        self.assertFalse(endpoints["dispatch_verified"])
        tampered = copy.deepcopy(result.trace)
        tampered[0]["reward_components"]["goal"] = 100
        self.assertFalse(verify_trace(make_env, tampered, seed=3).ok)

    def test_lab_sparse_reward_and_component_audit(self):
        env = build_electrolyte_line_env(RewardSpec.sparse_goal())
        env.reset(seed=2)
        action = Action("start_skill", {
            "skill_id": "run_electrolyte_cell_line", "request_id": "start",
            "parameters_by_step": {"mix": {"recipe": {}, "batch_size_ml": 10}},
        })
        self.assertEqual(env.step(action).reward, 0)
        self.assertEqual(env.step(action).reward, 0)
        result = env.step(Action("advance_time", {"minutes": 905}))
        self.assertEqual(result.reward, 10)
        self.assertEqual(sum(result.info["reward_components"].values()), result.reward)
        result.info["reward_components"]["goal"] = 1234
        self.assertEqual(env.trace()[-1]["reward_components"]["goal"], 10)
        self.assertTrue(verify_trace(
            lambda: build_electrolyte_line_env(RewardSpec.sparse_goal()), env.trace(), seed=2
        ).ok)


if __name__ == "__main__":
    unittest.main()
