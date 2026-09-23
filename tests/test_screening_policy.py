import unittest
from copy import deepcopy

from matlabgym.benchmark import TrialSlot
from matlabgym.core import Observation
from matlabgym.policies import ScreeningPolicy, policy_factory


def observation(measurements=(), **changes):
    state = {
        "candidates": [
            {"formulation_id": fid, "ec": ec, "pc": 0.0, "emc": 1 - ec, "salt_m": 1.0}
            for fid, ec in (("low", 0.0), ("near_low", 0.1), ("high", 1.0), ("near_high", 0.9))
        ],
        "measurements": list(measurements),
        "support_mask": [[fid, 30] for fid in ("low", "near_low", "high", "near_high")],
        "jobs": {},
        "clock_min": 0,
        "budgets": {"measurements_remaining": 5},
    }
    state.update(changes)
    return Observation(0, 5, (), state)


def measurement(fid, value):
    return {"formulation_id": fid, "temperature_c": 30, "conductivity_ms_cm": value}


def selected(action):
    return action.parameters["parameters_by_step"]["mix"]["formulation_id"]


class ScreeningPolicyTests(unittest.TestCase):
    def test_feedback_changes_adaptive_selection(self):
        low_high = observation([measurement("low", 2), measurement("high", 12)])
        high_low = observation([measurement("low", 12), measurement("high", 2)])
        assert selected(ScreeningPolicy()(low_high)) == "near_high"
        assert selected(ScreeningPolicy()(high_low)) == "near_low"

    def test_only_observed_feedback_is_used_and_input_is_unchanged(self):
        obs = observation()
        for item in obs.public_state["candidates"]:
            item["conductivity_ms_cm"] = 1000 if item["formulation_id"] == "high" else 0
        before = deepcopy(obs.to_dict())
        assert selected(ScreeningPolicy()(obs)) == "low"
        assert obs.to_dict() == before

    def test_missing_composition_falls_back_to_public_order(self):
        obs = observation([measurement("low", 2), measurement("high", 12)])
        obs.public_state["candidates"][0]["ec"] = None
        assert selected(ScreeningPolicy()(obs)) == "near_low"

    def test_running_jobs_are_awaited_and_request_ids_are_unique(self):
        obs = observation(
            jobs={"j": {"status": "running", "estimated_completion_min": 75}}, clock_min=10
        )
        policy = ScreeningPolicy()
        first, second = policy(obs), policy(obs)
        assert first.name == "advance_time"
        assert first.parameters["minutes"] == 65
        assert first.parameters["request_id"] != second.parameters["request_id"]

    def test_random_factory_is_reproducible_and_instances_do_not_share_state(self):
        first = policy_factory(3, mode="random", seed=42)
        second = policy_factory(3, mode="random", seed=42)
        expected = [first(observation()).to_dict() for _ in range(8)]
        assert [second(observation()).to_dict() for _ in range(8)] == expected

    def test_support_and_measurement_budget_are_respected(self):
        assert selected(ScreeningPolicy()(observation(support_mask=[["high", 30]]))) == "high"
        assert ScreeningPolicy()(observation(support_mask=[])) is None
        assert ScreeningPolicy()(observation(budgets={"measurements_remaining": 0})) is None

    def test_factory_accepts_runner_trial_slots(self):
        slot = TrialSlot("slot", "hash", "task", "group", 23, 0, "random")
        from_slot = policy_factory(slot, mode="random")
        standalone = policy_factory(23, mode="random")
        assert from_slot(observation()).to_dict() == standalone(observation()).to_dict()


if __name__ == "__main__":
    unittest.main()
