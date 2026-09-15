"""Command-line demo for both planning and evidence-driven decision layers."""

from __future__ import annotations

import argparse
import json
from typing import Iterable, Optional

from .core import Action
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
    return {"layer": "planning", "final_state": env.observe().public_state, "last_outcome": env.last_outcome}


def run_decision_demo(seed: int = 7) -> dict:
    task, oracle = make_fixture_task()
    env = ElectrolyteReplayEnv(task, oracle, seed=seed)
    # A transparent baseline: evaluate candidates in public order.
    for action in env.available_actions():
        result = env.step(action)
        if result.terminated:
            break
    return {"layer": "decision", "evaluation": env.evaluate(), "trace": env.trace()}


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(list(argv) if argv is not None else None)
    print(json.dumps({"planning": run_planning_demo(), "decision": run_decision_demo(args.seed)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
