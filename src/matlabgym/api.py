"""Versioned structural API shared by scientific environment backends."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Dict, Mapping, Optional, Protocol, Tuple, runtime_checkable

from .benchmark import EpisodeOutcome, stable_hash
from .core import Action, Observation, StepResult

API_VERSION = "1.0"


def canonical_action(action: Any) -> Action:
    """Preserve valid payloads; encode non-JSON input as a replayable rejection."""
    try:
        if not isinstance(action, Action) or not isinstance(action.parameters, Mapping):
            raise ValueError("invalid action")
        if not isinstance(action.name, str):
            raise ValueError("invalid action name")
        stable_hash(action.to_dict())
        return deepcopy(action)
    except (TypeError, ValueError, OverflowError):
        return Action("__invalid_payload__", {})


@runtime_checkable
class ScientificEnv(Protocol):
    task: Any
    manifest: Any
    episode_id: str
    terminated: bool
    truncated: bool

    @property
    def budget_spec(self) -> Mapping[str, Any]: ...

    def reset(
        self, *, seed: Optional[int] = None, options: Optional[Mapping[str, Any]] = None
    ) -> Tuple[Observation, Mapping[str, Any]]: ...
    def step(self, action: Action) -> StepResult: ...
    def observe(self) -> Observation: ...
    def public_snapshot(self) -> Dict[str, Any]: ...
    def action_specs(self) -> Tuple[Dict[str, Any], ...]: ...
    def trace(self) -> list: ...
    def evaluate(self) -> Dict[str, Any]: ...
    def episode_outcome(self) -> EpisodeOutcome: ...


def normalize_results(results) -> list:
    """Detach operation outcomes and fill the common public result envelope."""
    normalized = []
    for item in results:
        value = item.to_dict() if hasattr(item, "to_dict") else item
        if not isinstance(value, Mapping):
            raise ValueError("each result must be an object")
        result = {
            "success": False,
            "status": None,
            "request_id": None,
            "job_id": None,
            "produced_artifact_ids": [],
            "failure_code": None,
            "failure_reason": None,
            "retryable": False,
            "replayed": False,
            **value,
        }
        artifacts = result["produced_artifact_ids"]
        if artifacts is None:
            artifacts = []
        if not isinstance(artifacts, (list, tuple)):
            raise ValueError("produced_artifact_ids must be an array")
        result["produced_artifact_ids"] = list(artifacts)
        normalized.append(deepcopy(result))
    return normalized


def _normalize_costs(costs) -> list:
    normalized = []
    for item in costs:
        if not isinstance(item, Mapping):
            raise ValueError("each cost must be an object")
        quantity = item.get("quantity")
        try:
            finite = (
                not isinstance(quantity, bool)
                and isinstance(quantity, (int, float))
                and math.isfinite(quantity)
            )
        except OverflowError:
            finite = False
        if not finite or quantity < 0:
            raise ValueError("cost quantity must be finite and non-negative")
        unit = item.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError("cost unit must be a non-empty string")
        source = item.get("source")
        if source not in ("observed", "configured", "proxy", "unknown"):
            raise ValueError("cost source must be observed, configured, proxy or unknown")
        normalized.append({"quantity": quantity, "unit": unit, "source": source})
    return normalized


def make_info(
    *,
    episode_id,
    manifest_hash,
    public_state,
    backend,
    results=(),
    reward_components=None,
    failure_code=None,
    costs=(),
    **extra,
) -> dict:
    """Build detached common metadata; extensions cannot replace reserved keys."""
    reserved = {
        "api_version",
        "episode_id",
        "manifest_hash",
        "state_hash",
        "results",
        "reward_components",
        "failure_code",
        "provenance",
        "costs",
    }
    conflicts = reserved.intersection(extra)
    if conflicts:
        raise ValueError("reserved info fields: %s" % sorted(conflicts))
    payload = {
        "api_version": API_VERSION,
        "episode_id": episode_id,
        "manifest_hash": manifest_hash,
        "state_hash": stable_hash(public_state),
        "results": normalize_results(results),
        "reward_components": {} if reward_components is None else reward_components,
        "failure_code": failure_code,
        "provenance": {"backend": backend},
        "costs": _normalize_costs(costs),
        **extra,
    }
    return deepcopy(payload)
