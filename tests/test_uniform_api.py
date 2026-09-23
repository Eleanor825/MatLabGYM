"""Shared contracts exercised through real deterministic episodes."""

import copy
import unittest

from matlabgym.api import API_VERSION, ScientificEnv, make_info, normalize_results
from matlabgym.benchmark import EpisodeOutcome, stable_hash
from matlabgym.core import Action, Observation, StepResult
from matlabgym.domains.electrolyte_line import build_electrolyte_line_env
from matlabgym.planning import PlanningEnv
from matlabgym.replay import verify_trace


class UniformApiTests(unittest.TestCase):
    def test_serializers_detach_nested_payloads(self):
        action = Action("x", {"nested": [1]})
        observation = Observation(
            0, 1, ({"parameters": {"x": []}},), {"nested": [2]}, {"nested": [3]}
        )
        result = StepResult(observation, 1.0, False, False, {"nested": [4]})
        action.to_dict()["parameters"]["nested"].append(9)
        exported = result.to_dict()
        exported["observation"]["available_actions"][0]["parameters"]["x"].append(9)
        exported["observation"]["public_state"]["nested"].append(9)
        exported["observation"]["last_outcome"]["nested"].append(9)
        exported["info"]["nested"].append(9)
        self.assertEqual(action.parameters, {"nested": [1]})
        self.assertEqual(observation.public_state, {"nested": [2]})
        self.assertEqual(observation.last_outcome, {"nested": [3]})
        self.assertEqual(observation.available_actions[0]["parameters"]["x"], [])
        self.assertEqual(result.info, {"nested": [4]})
        self.assertEqual(tuple(result), (observation, 1.0, False, False, result.info))

    def test_common_info_is_detached_and_reserved(self):
        results = [{"value": []}]
        extra = {"nested": []}
        info = make_info(
            episode_id="a",
            manifest_hash="m",
            public_state={"x": 1},
            backend="test",
            results=results,
            extension=extra,
            costs=[{"quantity": 1, "unit": "query", "source": "proxy"}],
        )
        self.assertEqual(info["api_version"], API_VERSION)
        self.assertEqual(info["state_hash"], stable_hash({"x": 1}))
        self.assertEqual(info["provenance"], {"backend": "test"})
        info["results"][0]["value"].append(1)
        info["extension"]["nested"].append(1)
        self.assertEqual(results, [{"value": []}])
        self.assertEqual(extra, {"nested": []})
        for key in ("api_version", "state_hash", "provenance"):
            with self.assertRaises(ValueError):
                make_info(
                    episode_id="a",
                    manifest_hash="m",
                    public_state={},
                    backend="test",
                    **{key: None},
                )

    def test_result_normalization_preserves_extensions(self):
        normalized = normalize_results(
            [{"measurement": {"values": [1]}, "produced_artifact_ids": ("artifact-1",)}]
        )[0]
        self.assertFalse(normalized["success"])
        self.assertFalse(normalized["retryable"])
        self.assertFalse(normalized["replayed"])
        for name in ("status", "request_id", "job_id", "failure_code", "failure_reason"):
            self.assertIsNone(normalized[name])
        self.assertEqual(normalized["produced_artifact_ids"], ["artifact-1"])
        self.assertEqual(normalized["measurement"], {"values": [1]})
        with self.assertRaises(ValueError):
            normalize_results(["not an object"])

    def test_cost_validation(self):
        valid = {"quantity": 1, "unit": "configured_cost_unit", "source": "configured"}

        def build(cost):
            return make_info(
                episode_id="a", manifest_hash="m", public_state={}, backend="test", costs=[cost]
            )

        for source in ("observed", "configured", "proxy", "unknown"):
            self.assertEqual(build({**valid, "source": source})["costs"][0]["source"], source)
        for quantity in (-1, float("nan"), float("inf"), True, "1", None, 10**1000):
            with self.subTest(quantity=str(quantity)[:30]), self.assertRaises(ValueError):
                build({**valid, "quantity": quantity})
        for field, value in (
            ("source", "simulator"),
            ("source", None),
            ("unit", " "),
            ("unit", None),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                build({**valid, field: value})

    def test_lab_action_parameter_contracts(self):
        env = build_electrolyte_line_env()
        specs = {item["name"]: item for item in env.action_specs()}
        mix = specs["start_operation"]["registry"]["mix_electrolyte"]
        self.assertEqual(set(mix["parameter_schema"]["required"]), {"recipe", "batch_size_ml"})
        self.assertEqual(mix["parameter_schema"]["properties"]["batch_size_ml"]["minimum"], 1.0)
        self.assertFalse(mix["input_contract"]["required"])
        characterization = specs["start_operation"]["registry"]["characterize_electrolyte"]
        self.assertTrue(characterization["input_contract"]["required"])
        skill = specs["start_skill"]["registry"]["run_electrolyte_cell_line"]
        self.assertEqual(skill["parameters_by_step_schema"]["required"], ["mix"])
        self.assertEqual(
            skill["parameters_by_step_schema"]["properties"]["characterize"]["required"], []
        )
        env.reset()
        cost = env.step(Action("poll")).info["costs"][0]
        self.assertEqual(
            cost, {"quantity": 0.0, "unit": "configured_cost_unit", "source": "configured"}
        )

    def assert_contract(self, env):
        self.assertIsInstance(env, ScientificEnv)
        observation, info = env.reset(seed=9)
        self.assertIsInstance(observation, Observation)
        self.assertEqual(info["state_hash"], stable_hash(env.public_snapshot()))
        self.assertEqual(info["api_version"], "1.0")
        self.assertEqual(info["results"], [])
        self.assertIsNone(info["failure_code"])
        for action in env.action_specs():
            self.assertEqual(action["parameters"]["type"], "object")
        with self.assertRaises(ValueError):
            env.reset(options={"unsupported": True})
        self.assertEqual(env.trace(), [])
        self.assertIsInstance(env.episode_outcome(), EpisodeOutcome)

    def test_planning_normal_episode_and_replay(self):
        env = PlanningEnv()
        self.assert_contract(env)
        rewards = []
        for name in ("prepare_electrolyte", "assemble_cell", "formation", "cycle", "characterize"):
            observation, reward, terminated, truncated, info = env.step(Action(name))
            rewards.append(reward)
            self.assertEqual(info["state_hash"], stable_hash(observation.public_state))
        self.assertEqual(rewards, [1, 1, 1, 1, 6])
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertTrue(env.evaluate()["success"])
        self.assertTrue(env.episode_outcome().goal_reached)
        self.assertFalse(env.episode_outcome().scientifically_validated)
        self.assertTrue(verify_trace(PlanningEnv, env.trace(), seed=9).ok)
        snapshot = env.public_snapshot()
        snapshot["formed"] = False
        trace = env.trace()
        trace[0]["after"]["electrolyte_prepared"] = False
        self.assertTrue(env.public_snapshot()["formed"])
        self.assertTrue(env.trace()[0]["after"]["electrolyte_prepared"])
        env.reset(seed=9)
        self.assertFalse(env.observe().public_state["characterized"])
        self.assertFalse(env.evaluate()["success"])

    def test_lab_normal_episode_and_trace_evaluation(self):
        env = build_electrolyte_line_env()
        self.assert_contract(env)
        recipe = {
            "components": [
                {"material": "EC", "fraction": 0.3},
                {"material": "EMC", "fraction": 0.7},
                {"material": "LiPF6", "concentration_m": 1.0},
            ]
        }
        env.step(
            Action(
                "start_skill",
                {
                    "skill_id": "run_electrolyte_cell_line",
                    "parameters_by_step": {"mix": {"recipe": recipe, "batch_size_ml": 20.0}},
                },
            )
        )
        result = env.step(Action("advance_time", {"minutes": 905}))
        self.assertTrue(result.terminated)
        self.assertTrue(env.evaluate()["success"])
        self.assertEqual(env.episode_outcome().total_reward, sum(e["reward"] for e in env.trace()))
        self.assertFalse(env.episode_outcome().physical_completed)
        self.assertTrue(verify_trace(build_electrolyte_line_env, env.trace(), seed=9).ok)
        report = copy.deepcopy(env.evaluate())
        env.runtime.artifacts.clear()
        self.assertEqual(report, env.evaluate())
        specs = env.action_specs()
        specs[0]["registry"].clear()
        self.assertTrue(env.action_specs()[0]["registry"])

    def test_non_json_actions_have_replayable_rejections(self):
        for factory in (PlanningEnv, build_electrolyte_line_env):
            with self.subTest(environment=factory.__name__):
                env = factory()
                env.reset(seed=7)
                result = env.step(Action("poll", {"value": float("nan")}))
                self.assertEqual(
                    env.trace()[0]["action"], {"name": "__invalid_payload__", "parameters": {}}
                )
                self.assertTrue(verify_trace(factory, env.trace(), seed=7).ok)
                if factory is build_electrolyte_line_env:
                    self.assertEqual(result.info["failure_code"], "INVALID_PARAMETER")
                    self.assertEqual(
                        result.info["results"][0]["failure_reason"], "non-JSON action payload"
                    )
                else:
                    self.assertEqual(result.observation.last_outcome, result.info)
                    result.info["results"][0]["failure_reason"] = "changed"
                    self.assertNotEqual(
                        env.observe().last_outcome["results"][0]["failure_reason"], "changed"
                    )

    def test_lab_rejects_unknown_command_parameters(self):
        env = build_electrolyte_line_env()
        env.reset(seed=7)
        result = env.step(Action("poll", {"unsupported": True}))
        self.assertEqual(result.info["failure_code"], "INVALID_PARAMETER")
        self.assertIn("unsupported", result.info["results"][0]["failure_reason"])
        self.assertTrue(verify_trace(build_electrolyte_line_env, env.trace(), seed=7).ok)

    def test_planning_rejection_preserves_state_and_costs_step(self):
        env = PlanningEnv(max_steps=1)
        observation, reward, terminated, truncated, info = env.step(Action("formation"))
        self.assertEqual(reward, -1)
        self.assertFalse(terminated)
        self.assertTrue(truncated)
        self.assertEqual(observation.budget_remaining, 0)
        self.assertEqual(info["failure_code"], "INVALID_ACTION")
        self.assertEqual(env.episode_outcome().failure_categories, ("invalid_action",))


if __name__ == "__main__":
    unittest.main()
