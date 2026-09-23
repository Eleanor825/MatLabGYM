"""Observation-only baselines for the electrolyte screening task.

The adaptive baseline uses nearest-neighbor conductivity estimates from this
episode's observed measurements. It is a small greedy heuristic, not Bayesian
optimization or a scientifically validated optimizer. Feature distances are
unscaled Euclidean distances over the four public composition fields.
"""

from __future__ import annotations

import math
import random
from typing import Any, Mapping, Optional, Union

from .benchmark import TrialSlot
from .core import Action, Observation


class ScreeningPolicy:
    """One policy instance per trial; no oracle or environment reference needed.

    ``public_order`` has a stateless selection rule. Only request numbering and
    the instance-local random generator carry state between calls.
    """

    MODES = ("public_order", "random", "adaptive")

    def __init__(self, mode: str = "adaptive", seed: int = 0, temperature: int = 30):
        if mode not in self.MODES:
            raise ValueError("unknown screening policy: %s" % mode)
        self.mode = mode
        self.temperature = temperature
        self._rng = random.Random(seed)
        self._request_number = 0

    def _action(self, name: str, parameters: Mapping[str, Any]) -> Action:
        self._request_number += 1
        return Action(name, dict(parameters, request_id="policy-%06d" % self._request_number))

    @staticmethod
    def _features(candidate: Mapping[str, Any]) -> Optional[tuple[float, ...]]:
        try:
            values = tuple(float(candidate[key]) for key in ("ec", "pc", "emc", "salt_m"))
        except (KeyError, TypeError, ValueError):
            return None
        return values if all(math.isfinite(value) for value in values) else None

    def __call__(self, observation: Observation) -> Optional[Action]:
        state = observation.public_state
        running = [job for job in state.get("jobs", {}).values() if job["status"] == "running"]
        if running:
            eta = min(float(job["estimated_completion_min"]) for job in running)
            return self._action("advance_time", {"minutes": max(0.0, eta - state["clock_min"])})

        measured = {
            row["formulation_id"]: row
            for row in state.get("measurements", [])
            if row["temperature_c"] == self.temperature
        }
        support = {(str(fid), temperature) for fid, temperature in state.get("support_mask", [])}
        candidates = list(state.get("candidates", []))
        remaining = [
            candidate
            for candidate in candidates
            if candidate["formulation_id"] not in measured
            and (candidate["formulation_id"], self.temperature) in support
        ]
        if not remaining or state.get("budgets", {}).get("measurements_remaining", 1) <= 0:
            return None

        selected = remaining[0]
        if self.mode == "random":
            selected = self._rng.choice(remaining)
        elif self.mode == "adaptive" and measured:
            features = {item["formulation_id"]: self._features(item) for item in candidates}
            # Incomplete metadata has no defensible distance; use public order.
            if all(value is not None for value in features.values()):
                observed = [fid for fid in features if fid in measured]
                if observed:

                    def estimate(candidate: Mapping[str, Any]) -> float:
                        target = features[candidate["formulation_id"]]
                        nearest = min(
                            observed,
                            key=lambda fid: sum(
                                (left - right) ** 2 for left, right in zip(target, features[fid])
                            ),
                        )
                        return float(measured[nearest]["conductivity_ms_cm"])

                    selected = max(remaining, key=estimate)

        return self._action(
            "start_skill",
            {
                "skill_id": "measure_electrolyte",
                "parameters_by_step": {
                    "mix": {"formulation_id": selected["formulation_id"], "batch_size_ml": 20},
                    "characterize": {"temperature_c": self.temperature},
                },
            },
        )


def policy_factory(
    slot: Union[TrialSlot, int], *, mode: str = "adaptive", seed: int = 0, temperature: int = 30
) -> ScreeningPolicy:
    """Create fresh trial state using the slot seed plus an optional seed offset.

    Accept a runner TrialSlot, or an integer seed for a standalone episode.
    Bind keyword options with functools.partial for use with run_cohort.
    """
    trial_seed = slot.seed if isinstance(slot, TrialSlot) else slot
    return ScreeningPolicy(mode, seed=seed + trial_seed, temperature=temperature)
