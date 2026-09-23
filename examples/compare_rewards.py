"""Compare reward returns on matched policies; no training or model API required.

Default data is a synthetic fixture. --csv accepts the replay schema described
in README; importing a CSV does not establish scientific calibration.
"""

import argparse
import json
import random
from pathlib import Path
from statistics import mean

from matlabgym import Action, ReplayRewardSpec, TaskSpec, TrialSlot, run_cohort
from matlabgym.electrolyte import CSVReplayOracle, ElectrolyteReplayEnv, make_fixture_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--target", type=float, default=12.0)
    parser.add_argument("--budget", type=int, default=5)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.seeds <= 0:
        parser.error("--seeds must be positive")
    oracle = CSVReplayOracle.from_csv(args.csv) if args.csv else make_fixture_task()[1]
    task = TaskSpec("electrolyte.reward-demo.v1", "Find a supported formulation meeting target",
                    args.budget, args.budget, args.target)
    scale = abs(args.target) or 1.0
    presets = {
        "sparse": ReplayRewardSpec.sparse_goal(scale=scale),
        "improvement": ReplayRewardSpec.improvement(scale=scale),
        "cost_aware": ReplayRewardSpec.cost_aware(scale=scale),
    }
    summaries = []
    trials = []
    for reward_name, spec in presets.items():
        for method in ("public_order", "random"):
            environments = {}

            def env_factory(slot, reward_spec=spec, instances=environments):
                env = ElectrolyteReplayEnv(task, oracle, reward=reward_spec)
                instances[slot.slot_id] = env
                return env

            template = ElectrolyteReplayEnv(task, oracle, reward=spec)
            slots = [TrialSlot(
                "%s-%s-%s" % (reward_name, method, seed), template.manifest.manifest_hash,
                task.task_id, "single-demo-task", seed, 0, method,
                budget_spec=template.budget_spec,
            ) for seed in range(args.seeds)]

            def policy_factory(slot, policy_name=method):
                rng = random.Random(slot.seed)

                def policy(observation):
                    actions = observation.available_actions
                    if not actions:
                        return None
                    selected = rng.choice(actions) if policy_name == "random" else actions[0]
                    return Action(selected["name"], selected["parameters"])

                return policy

            cohort = run_cohort(slots, env_factory, policy_factory=policy_factory)
            metrics = [environments[o.slot.slot_id].evaluate() for o in cohort.outcomes]
            summaries.append({
                "reward": reward_name, "policy": method,
                "manifest_hash": template.manifest.manifest_hash,
                "reward_spec": spec.to_dict(), "n_assigned": cohort.n_assigned,
                "status_counts": cohort.status_counts,
                "success_rate": mean(o.score for o in cohort.outcomes),
                "mean_return": mean(o.outcome.total_reward for o in cohort.outcomes),
                "mean_measurements": mean(m["measurements"] for m in metrics),
                "mean_simple_regret_ms_cm": mean(m["simple_regret_ms_cm"] for m in metrics),
            })
            trials.extend({"trial": o.to_dict(), "evaluation": m}
                          for o, m in zip(cohort.outcomes, metrics))
    payload = {
        "scope": "unvalidated CSV replay" if args.csv else "synthetic fixture smoke test",
        "comparison": "matched policies; reward changes do not train or improve the policies",
        "cost_source": "proxy", "cost_unit": "measurement_query",
        "summaries": summaries, "trials": trials,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in payload.items() if k != "trials"}, indent=2))


if __name__ == "__main__":
    main()
