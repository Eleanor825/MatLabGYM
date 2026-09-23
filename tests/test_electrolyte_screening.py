import copy
import unittest
from dataclasses import replace

from matlabgym import (
    Action,
    ElectrolyteEnv,
    ElectrolyteReplayEnv,
    ElectrolyteTask,
    PlanningEnv,
    ReplayRewardSpec,
    ScientificEnv,
    TrialSlot,
    build_electrolyte_line_env,
    make_fixture_task,
    run_cohort,
)
from matlabgym.electrolyte import CSVReplayOracle
from matlabgym.policies import policy_factory
from matlabgym.replay import verify_trace


def environment(**options):
    task = ElectrolyteTask(**options)
    return ElectrolyteEnv(task, make_fixture_task()[1])


def skill(fid, request_id):
    return Action(
        "start_skill",
        {
            "skill_id": "measure_electrolyte",
            "request_id": request_id,
            "parameters_by_step": {"mix": {"formulation_id": fid, "batch_size_ml": 20}},
        },
    )


def mix(fid, request_id):
    return Action(
        "start_operation",
        {
            "operation_id": "mix_electrolyte",
            "request_id": request_id,
            "parameters": {"formulation_id": fid, "batch_size_ml": 20},
        },
    )


def characterize(artifact_id, request_id):
    return Action(
        "start_operation",
        {
            "operation_id": "characterize_electrolyte",
            "input_id": artifact_id,
            "request_id": request_id,
            "parameters": {"temperature_c": 30},
        },
    )


class ScreeningTests(unittest.TestCase):
    def test_same_seed_reset_cannot_reuse_previous_episode_artifact(self):
        env = environment()
        env.reset(seed=1)
        env.step(mix("E01", "first"))
        result = env.step(Action("advance_time", {"minutes": 30}))
        old_id = result.info["results"][0]["produced_artifact_ids"][0]
        env.reset(seed=1)
        env.step(mix("E01", "first"))
        result = env.step(Action("advance_time", {"minutes": 30}))
        new_id = result.info["results"][0]["produced_artifact_ids"][0]
        self.assertNotEqual(old_id, new_id)
        self.assertIsNotNone(env.step(characterize(old_id, "old")).info["failure_code"])
        check = verify_trace(environment, env.trace(), seed=1)
        self.assertTrue(check.ok, check.reason)

    def test_csv_does_not_silently_round_conditions_or_admit_nan(self):
        base = {"formulation_id": "F", "temperature_c": "30", "conductivity_ms_cm": "4"}
        for values in (
            {"temperature_c": "30.5"},
            {"conductivity_ms_cm": "nan"},
            {"uncertainty_ms_cm": "-1"},
            {"formulation_id": ""},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                CSVReplayOracle([{**base, **values}])

    def test_single_operations_bind_measurement_to_completed_sample(self):
        env = environment()
        env.reset(seed=4)
        rejected = env.step(characterize("missing", "bad"))
        self.assertIsNotNone(rejected.info["failure_code"])
        accepted = env.step(mix("E01", "mix"))
        self.assertEqual(accepted.info["results"][0]["status"], "accepted")
        self.assertEqual(accepted.observation.public_state["artifacts"], {})
        self.assertEqual(accepted.observation.public_state["measurements"], [])
        finished = env.step(Action("advance_time", {"minutes": 30}))
        aid = finished.info["results"][0]["produced_artifact_ids"][0]
        env.step(characterize(aid, "measure"))
        partial = env.step(Action("advance_time", {"minutes": 44}))
        self.assertEqual(partial.observation.public_state["measurements"], [])
        result = env.step(Action("advance_time", {"minutes": 1}))
        report = result.info["results"][0]["produced_artifact_ids"][0]
        artifact = result.observation.public_state["artifacts"][report]
        self.assertEqual(artifact["parent_ids"], [aid])
        self.assertEqual(artifact["metadata"]["measurement"]["formulation_id"], "E01")
        self.assertEqual(env.evaluate()["measurements"], 1)
        self.assertTrue(verify_trace(environment, env.trace(), seed=4).ok)

    def test_atomic_skill_and_individual_tools_have_same_scientific_return(self):
        atomic, tools = environment(), environment()
        atomic.step(skill("E01", "atomic"))
        atomic.step(Action("advance_time", {"minutes": 75}))
        tools.step(mix("E01", "mix"))
        result = tools.step(Action("advance_time", {"minutes": 30}))
        aid = result.info["results"][0]["produced_artifact_ids"][0]
        tools.step(characterize(aid, "char"))
        tools.step(Action("advance_time", {"minutes": 45}))
        self.assertEqual(
            atomic.evaluate()["best_found_ms_cm"], tools.evaluate()["best_found_ms_cm"]
        )
        self.assertAlmostEqual(
            atomic.episode_outcome().total_reward, tools.episode_outcome().total_reward
        )
        self.assertEqual(atomic.runtime.clock_min, tools.runtime.clock_min)

    def test_request_replay_and_duplicate_measurement_do_not_pay_twice(self):
        env = environment(target_conductivity=100)
        action = skill("E01", "start")
        env.step(action)
        retry = env.step(action)
        self.assertTrue(retry.info["results"][0]["replayed"])
        wait = Action("advance_time", {"minutes": 75, "request_id": "wait"})
        env.step(wait)
        replay = env.step(wait)
        self.assertEqual(replay.reward, 0)
        self.assertEqual(replay.info["costs"][0]["quantity"], 0)
        self.assertEqual(env.evaluate()["measurements"], 1)
        duplicate = env.step(skill("E01", "another"))
        self.assertEqual(duplicate.info["failure_code"], "MEASUREMENT_ALREADY_REQUESTED")
        conflict = env.step(skill("E02", "start"))
        self.assertEqual(conflict.info["failure_code"], "REQUEST_CONFLICT")

    def test_concurrent_queries_reserve_budget_and_charge_each_completed_measurement(self):
        env = environment(
            max_measurements=2,
            target_conductivity=100,
            mixing_capacity=3,
            characterization_capacity=3,
        )
        env.step(skill("E01", "a"))
        env.step(skill("E02", "b"))
        blocked = env.step(skill("E03", "c"))
        self.assertEqual(blocked.info["failure_code"], "BUDGET_EXCEEDED")
        self.assertEqual(len(env.runtime.jobs), 2)
        result = env.step(Action("advance_time", {"minutes": 75}))
        self.assertEqual(len(result.info["new_measurements"]), 2)
        self.assertEqual(result.info["costs"][0]["quantity"], 2)
        self.assertAlmostEqual(result.info["reward_components"]["measurement_cost"], -0.1)
        self.assertTrue(result.truncated)
        self.assertFalse(result.terminated)

    def test_stop_characterization_quarantines_sample_and_releases_query_slot(self):
        env = environment(max_measurements=1)
        env.step(mix("E01", "m"))
        result = env.step(Action("advance_time", {"minutes": 30}))
        aid = result.info["results"][0]["produced_artifact_ids"][0]
        accepted = env.step(characterize(aid, "c"))
        job_id = accepted.info["results"][0]["job_id"]
        stopped = env.step(Action("stop_job", {"job_id": job_id}))
        self.assertEqual(stopped.observation.public_state["artifacts"][aid]["state"], "quarantined")
        self.assertEqual(stopped.observation.public_state["budgets"]["measurements_reserved"], 0)
        self.assertIsNotNone(env.step(characterize(aid, "retry")).info["failure_code"])
        self.assertEqual(env.step(skill("E02", "other")).info["failure_code"], None)
        result = env.step(Action("advance_time", {"minutes": 75}))
        self.assertTrue(result.terminated)
        self.assertEqual(env.evaluate()["measurements"], 1)

    def test_skill_cannot_be_stopped_and_deadline_does_not_release_hidden_result(self):
        env = environment(max_time_min=50)
        accepted = env.step(skill("E01", "s"))
        rejected = env.step(Action("stop_job", {"job_id": accepted.info["results"][0]["job_id"]}))
        self.assertEqual(rejected.info["failure_code"], "NOT_INTERRUPTIBLE")
        result = env.step(Action("advance_time", {"minutes": 1000}))
        self.assertEqual(env.runtime.clock_min, 50)
        self.assertEqual(env.evaluate()["measurements"], 0)
        self.assertTrue(result.truncated)
        self.assertFalse(result.terminated)

    def test_unknown_parameters_support_and_runtime_configuration_are_rejected(self):
        env = environment()
        self.assertEqual(
            env.step(Action("poll", {"extra": 1})).info["failure_code"], "INVALID_PARAMETER"
        )
        self.assertEqual(
            env.step(skill("UNMEASURED", "new")).info["failure_code"], "OUTSIDE_SUPPORT"
        )
        for name, value in (
            ("backend", "other"),
            ("schema_version", "other"),
            ("budget_money", 100),
        ):
            env = environment()
            setattr(env.runtime, name, value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                env.step(Action("poll"))

    def test_mutation_isolation_and_public_state_do_not_expose_unmeasured_outcomes(self):
        env = environment()
        result = env.step(skill("E01", "s"))
        self.assertNotIn("oracle_optimum_ms_cm", result.observation.public_state)
        self.assertEqual(result.observation.public_state["measurements"], [])
        result.info["results"][0]["job_id"] = "forged"
        result.observation.public_state["candidates"][0]["formulation_id"] = "forged"
        self.assertNotEqual(env.trace()[0]["results"][0]["job_id"], "forged")
        self.assertNotEqual(env.public_snapshot()["candidates"][0]["formulation_id"], "forged")
        completed = env.step(Action("advance_time", {"minutes": 75}))
        completed.info["new_measurements"][0]["conductivity_ms_cm"] = 999
        self.assertNotEqual(env.evaluate()["best_found_ms_cm"], 999)

    def test_all_four_environments_share_contract_and_invalid_trace_replay(self):
        task, oracle = make_fixture_task()
        factories = [
            PlanningEnv,
            build_electrolyte_line_env,
            environment,
            lambda: ElectrolyteReplayEnv(task, oracle),
        ]
        fields = {
            "api_version",
            "episode_id",
            "manifest_hash",
            "state_hash",
            "results",
            "reward_components",
            "failure_code",
            "costs",
            "provenance",
        }
        for factory in factories:
            with self.subTest(factory=factory):
                env = factory()
                self.assertIsInstance(env, ScientificEnv)
                _, info = env.reset(seed=8)
                self.assertTrue(fields <= info.keys())
                result = env.step(Action("poll", {"request_id": float("nan")}))
                self.assertEqual(len(tuple(result)), 5)
                self.assertTrue(fields <= result.info.keys())
                check = verify_trace(factory, env.trace(), seed=8)
                self.assertTrue(check.ok, check.reason)

    def test_cohort_and_cost_provenance_replay(self):
        env = environment()
        slots = [
            TrialSlot(
                str(i),
                env.manifest.manifest_hash,
                env.task.task_id,
                "fixture",
                i,
                0,
                "adaptive",
                budget_spec=env.budget_spec,
            )
            for i in range(3)
        ]
        result = run_cohort(
            slots, lambda _: environment(), policy_factory=policy_factory, bootstrap_samples=20
        )
        self.assertEqual(result.n_retained, 3)
        self.assertTrue(all(o.outcome.goal_reached for o in result.outcomes))
        trace = copy.deepcopy(result.outcomes[0].trace)
        trace[-1]["info"]["costs"][0]["quantity"] = 0
        self.assertFalse(verify_trace(environment, trace, seed=0).ok)

    def test_reward_configuration_and_goal_remain_independent(self):
        task = ElectrolyteTask()
        a = ElectrolyteEnv(task, make_fixture_task()[1], reward=ReplayRewardSpec.sparse_goal())
        b = ElectrolyteEnv(
            task, make_fixture_task()[1], reward=ReplayRewardSpec.cost_aware(scale=12)
        )
        for action in (skill("E02", "s"), Action("advance_time", {"minutes": 75})):
            left, right = a.step(action), b.step(action)
        self.assertEqual(a.evaluate(), b.evaluate())
        self.assertNotEqual(left.reward, right.reward)
        b.task = replace(task, max_measurements=100)
        with self.assertRaises(ValueError):
            b.reset()


if __name__ == "__main__":
    unittest.main()
