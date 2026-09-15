import unittest

from matlabgym.core import Action
from matlabgym.electrolyte import ElectrolyteReplayEnv, make_fixture_task
from matlabgym.planning import PlanningEnv


class PlanningTests(unittest.TestCase):
    def test_preconditions_and_goal(self):
        env = PlanningEnv()
        invalid = env.step(Action("cycle"))
        self.assertFalse(invalid.info["valid"])
        for name in ["prepare_electrolyte", "assemble_cell", "formation", "cycle", "characterize"]:
            result = env.step(Action(name))
        self.assertTrue(result.terminated)
        self.assertTrue(result.info["success"])


class DecisionTests(unittest.TestCase):
    def test_seed_reproducibility_and_metrics(self):
        task, oracle = make_fixture_task()
        first = ElectrolyteReplayEnv(task, oracle, seed=3)
        second = ElectrolyteReplayEnv(task, oracle, seed=3)
        for a in first.available_actions():
            first.step(a)
            if first.terminated:
                break
        for a in second.available_actions():
            second.step(a)
            if second.terminated:
                break
        self.assertEqual(first.trace(), second.trace())
        self.assertEqual(first.evaluate(), second.evaluate())

    def test_duplicate_is_rejected_without_consuming_budget(self):
        task, oracle = make_fixture_task()
        env = ElectrolyteReplayEnv(task, oracle)
        action = env.available_actions()[0]
        env.step(action)
        remaining = env.budget_remaining
        result = env.step(action)
        self.assertFalse(result.info["valid"])
        self.assertEqual(env.budget_remaining, remaining)


if __name__ == "__main__":
    unittest.main()
