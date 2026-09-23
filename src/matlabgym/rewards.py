"""Designer-owned rewards; independent of oracle outcomes and success metrics."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ReplayRewardSpec:
    """Versioned scalarization for finite-support, maximization experiments.

    Improvement is the change in max(baseline, best observed value), divided
    by an explicitly configured scale. It never consults the hidden optimum.
    Query cost is a unitless proxy, not money or laboratory wall-clock time.
    """

    version: str = "replay-improvement-v1"
    goal_bonus: float = 1.0
    improvement_weight: float = 1.0
    measurement_cost: float = 0.0
    invalid_penalty: float = 1.0
    baseline: float = 0.0
    scale: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("reward version must be non-empty")
        for name in (
            "goal_bonus", "improvement_weight", "measurement_cost", "invalid_penalty",
            "baseline", "scale",
        ):
            value = getattr(self, name)
            try:
                valid = (
                    not isinstance(value, bool)
                    and isinstance(value, (int, float))
                    and math.isfinite(value)
                )
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError("%s must be finite" % name)
            if name != "baseline" and value < 0:
                raise ValueError("%s must be non-negative" % name)
        if self.scale <= 0:
            raise ValueError("scale must be positive")

    @classmethod
    def sparse_goal(cls, **overrides) -> "ReplayRewardSpec":
        values = {"version": "replay-sparse-v1", "improvement_weight": 0.0}
        values.update(overrides)
        return cls(**values)

    @classmethod
    def improvement(cls, **overrides) -> "ReplayRewardSpec":
        values = {"version": "replay-improvement-v1"}
        values.update(overrides)
        return cls(**values)

    @classmethod
    def cost_aware(cls, **overrides) -> "ReplayRewardSpec":
        values = {"version": "replay-cost-aware-v1", "measurement_cost": 0.05}
        values.update(overrides)
        return cls(**values)

    def components(
        self,
        *,
        valid: bool,
        previous_best: Optional[float],
        current_best: Optional[float],
        goal_reached: bool,
    ) -> Dict[str, float]:
        before = max(self.baseline, previous_best) if previous_best is not None else self.baseline
        after = max(self.baseline, current_best) if current_best is not None else self.baseline
        components = {
            "goal": self.goal_bonus if valid and goal_reached else 0.0,
            "improvement": self.improvement_weight * max(0.0, after - before) / self.scale
            if valid and self.improvement_weight else 0.0,
            "measurement_cost": -self.measurement_cost if valid else 0.0,
            "invalid_action": -self.invalid_penalty if not valid else 0.0,
        }
        if not all(math.isfinite(value) for value in components.values()) or not math.isfinite(
            sum(components.values())
        ):
            raise ValueError("reward overflow: increase scale or reduce weights")
        return components

    def to_dict(self) -> dict:
        return asdict(self)
