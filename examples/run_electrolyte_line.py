"""Run the six-stage electrolyte line as one non-interruptible skill."""

import json
from pathlib import Path

from matlabgym.core import Action
from matlabgym.domains import build_electrolyte_line_env


def main() -> None:
    env = build_electrolyte_line_env()
    _observation, reset_info = env.reset(seed=7)
    payload = json.loads(
        (Path(__file__).with_name("electrolyte_line_protocol.json")).read_text(encoding="utf-8")
    )
    accepted = env.step(Action("start_skill", payload))
    job_id = accepted.info["results"][0]["job_id"]

    # The template defines a skill as a multi-step action whose intermediate
    # execution cannot be controlled.  Stopping it is therefore rejected.
    stop_attempt = env.step(Action("stop_job", {"job_id": job_id, "request_id": "stop-001"}))
    finished = env.step(Action("advance_time", {"minutes": 1000, "request_id": "wait-001"}))

    print(
        json.dumps(
            {
                "reset": reset_info,
                "accepted": accepted.info,
                "stop_attempt": stop_attempt.info,
                "finished": finished.to_dict(),
                "trace": env.trace(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
