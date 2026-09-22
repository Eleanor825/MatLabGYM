"""Command-line demo for both planning and evidence-driven decision layers."""

from __future__ import annotations

import argparse
import json
from typing import Iterable, Optional

from .core import Action
from .domains import build_electrolyte_line_env
from .electrolyte import ElectrolyteReplayEnv, make_fixture_task
from .planning import PlanningEnv


def run_planning_demo() -> dict:
    env = PlanningEnv()
    # Deliberately try an invalid action first to show deterministic diagnosis.
    env.step(Action("cycle"))
    for name in ["prepare_electrolyte", "assemble_cell", "formation", "cycle", "characterize"]:
        result = env.step(Action(name))
        if result.terminated:
            break
    return {
        "layer": "planning",
        "final_state": env.observe().public_state,
        "last_outcome": env.last_outcome,
    }


def run_decision_demo(seed: int = 7) -> dict:
    task, oracle = make_fixture_task()
    env = ElectrolyteReplayEnv(task, oracle, seed=seed)
    # A transparent baseline: evaluate candidates in public order.
    for action in env.available_actions():
        result = env.step(action)
        if result.terminated:
            break
    return {"layer": "decision", "evaluation": env.evaluate(), "trace": env.trace()}


def run_lab_demo(seed: int = 7) -> dict:
    env = build_electrolyte_line_env()
    _, reset_info = env.reset(seed=seed)
    accepted = env.step(
        Action(
            "start_skill",
            {
                "skill_id": "run_electrolyte_cell_line",
                "request_id": "demo-line",
                "parameters_by_step": {
                    "mix": {
                        "recipe": {
                            "components": [
                                {"material": "EC", "fraction": 0.3},
                                {"material": "EMC", "fraction": 0.7},
                                {"material": "LiPF6", "concentration_m": 1.0},
                            ]
                        },
                        "batch_size_ml": 20.0,
                    }
                },
            },
        )
    )
    completed = env.step(Action("advance_time", {"minutes": 905, "request_id": "demo-wait"}))
    return {
        "layer": "lab-runtime",
        "reset": reset_info,
        "accepted": accepted.info["results"][0],
        "completed": completed.info["results"][0],
        "reward": completed.reward,
        "terminated": completed.terminated,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(list(argv) if argv is not None else None)
    print(
        json.dumps(
            {
                "planning": run_planning_demo(),
                "decision": run_decision_demo(args.seed),
                "lab": run_lab_demo(args.seed),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
