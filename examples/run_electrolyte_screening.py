"""Run an observation-driven screening loop and save verifiable evidence.

The default fixture is synthetic. CSV replay remains unvalidated: reproducible
execution and threshold attainment do not establish scientific validation.
"""

import argparse
import json
from pathlib import Path

from matlabgym.domains.electrolyte_screening import ElectrolyteEnv, ElectrolyteTask
from matlabgym.electrolyte import CSVReplayOracle, make_fixture_task
from matlabgym.policies import ScreeningPolicy, policy_factory
from matlabgym.replay import verify_trace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, help="Replay CSV; no scientific validation implied")
    parser.add_argument("--policy", choices=ScreeningPolicy.MODES, default="adaptive")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--budget", type=int, default=5, help="Maximum completed measurements")
    parser.add_argument("--target", type=float, default=12.0, help="Conductivity threshold, mS/cm")
    parser.add_argument("--output", type=Path, default=Path("runs/electrolyte-screening"))
    args = parser.parse_args()
    if args.budget < 1:
        parser.error("--budget must be positive")

    task = ElectrolyteTask(
        task_id="electrolyte.screening.csv" if args.csv else "electrolyte.screening.fixture",
        max_measurements=args.budget,
        target_conductivity=args.target,
    )

    def env_factory():
        oracle = CSVReplayOracle.from_csv(args.csv) if args.csv else make_fixture_task()[1]
        return ElectrolyteEnv(task=task, oracle=oracle)

    env = env_factory()
    observation, _ = env.reset(seed=args.seed)
    policy = policy_factory(0, mode=args.policy, seed=args.seed)
    for _ in range(task.max_steps):
        action = policy(observation)
        if action is None:
            break
        transition = env.step(action)
        observation = transition.observation
        if transition.terminated or transition.truncated:
            break

    trace = env.trace()
    verification = verify_trace(env_factory, trace, seed=args.seed)
    metrics = env.evaluate()
    args.output.mkdir(parents=True, exist_ok=True)
    payloads = {
        "manifest.json": env.manifest.to_dict(),
        "metrics.json": metrics,
        "trace.json": trace,
        "run.json": {
            "policy": args.policy,
            "seed": args.seed,
            "data_status": "unvalidated_csv" if args.csv else "synthetic_fixture",
            "scientific_validation_claimed": False,
            "replay_verification": verification.to_dict(),
        },
    }
    for name, payload in payloads.items():
        (args.output / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "metrics": metrics,
                "replay_verification": verification.to_dict(),
            },
            indent=2,
        )
    )
    if not verification.ok:
        raise SystemExit("Trace replay verification failed: %s" % verification.reason)


if __name__ == "__main__":
    main()
