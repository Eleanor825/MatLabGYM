"""Strict replay verification for Gym-style transition traces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from .benchmark import EndpointEvidence, EndpointName, TrialEndpoints, failure_category
from .core import Action
from .lab.contracts import stable_hash


class ReplayMismatch(AssertionError):
    """Raised when a trace cannot be reproduced from its recorded actions."""


@dataclass(frozen=True)
class ReplayVerification:
    ok: bool
    checked_steps: int
    mismatch_index: Optional[int] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_steps": self.checked_steps,
            "mismatch_index": self.mismatch_index,
            "reason": self.reason,
        }


def _snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return stable_hash(snapshot)


def verify_trace(
    env_factory: Callable[[], Any],
    trace: Sequence[Mapping[str, Any]],
    *,
    seed: int,
) -> ReplayVerification:
    """Replay every action and compare state, reward and terminal flags.

    The verifier intentionally compares the full public snapshot and not only a
    final score.  It is suitable for deterministic environments; stochastic
    environments must record and restore their oracle seed/state explicitly.
    """

    env = env_factory()
    env.reset(seed=seed)
    for index, expected in enumerate(trace):
        try:
            required_fields = {
                "episode_id",
                "manifest_hash",
                "action",
                "before",
                "after",
                "results",
                "endpoint_evidence",
                "reward",
                "terminated",
                "truncated",
            }
            missing = sorted(required_fields - set(expected))
            if missing:
                return ReplayVerification(False, index, index, "missing trace fields: %s" % missing)
            if expected["episode_id"] != env.episode_id:
                return ReplayVerification(False, index, index, "episode id mismatch")
            if expected["manifest_hash"] != env.manifest.manifest_hash:
                return ReplayVerification(False, index, index, "manifest hash mismatch")
            if _snapshot_hash(env.runtime.snapshot()) != _snapshot_hash(expected["before"]):
                return ReplayVerification(False, index, index, "before state mismatch")
            action = expected["action"]
            result = env.step(Action(str(action["name"]), dict(action.get("parameters") or {})))
            expected_after = expected["after"]
            if _snapshot_hash(result.observation.public_state) != _snapshot_hash(expected_after):
                return ReplayVerification(False, index + 1, index, "public state mismatch")
            if stable_hash(result.info.get("results", [])) != stable_hash(
                expected.get("results", [])
            ):
                return ReplayVerification(False, index + 1, index, "result payload mismatch")
            if stable_hash(result.info.get("endpoint_evidence", [])) != stable_hash(
                expected.get("endpoint_evidence", [])
            ):
                return ReplayVerification(False, index + 1, index, "endpoint evidence mismatch")
            if result.info.get("state_hash") != stable_hash(expected_after):
                return ReplayVerification(False, index + 1, index, "state hash mismatch")
            if result.reward != expected["reward"]:
                return ReplayVerification(False, index + 1, index, "reward mismatch")
            if result.terminated != expected["terminated"]:
                return ReplayVerification(False, index + 1, index, "terminated mismatch")
            if result.truncated != expected["truncated"]:
                return ReplayVerification(False, index + 1, index, "truncated mismatch")
        except Exception as exc:  # pragma: no cover - exact failure is returned to caller
            return ReplayVerification(False, index + 1, index, "%s: %s" % (type(exc).__name__, exc))
    return ReplayVerification(True, len(trace))


def endpoint_record_from_trace(trace: Mapping[str, Any]) -> TrialEndpoints:
    """Convert one environment trace into a fixed-denominator endpoint record."""
    results = trace.get("results") or []
    statuses = {str(item.get("status")) for item in results if isinstance(item, Mapping)}
    produced = tuple(
        artifact_id
        for item in results
        if isinstance(item, Mapping)
        for artifact_id in item.get("produced_artifact_ids", ())
    )
    endpoints = (
        EndpointEvidence(
            EndpointName.PLAN_MATERIALIZED,
            "accepted" in statuses or "completed" in statuses,
            "deterministic_compiler",
            produced,
        ),
        EndpointEvidence(
            EndpointName.DISPATCH_VERIFIED,
            "accepted" in statuses or "completed" in statuses,
            "deterministic_resource_reservation",
            produced,
        ),
        EndpointEvidence(
            EndpointName.STARTED,
            False,
            "not_claimed_by_simulator",
            reason="logical running state is not physical start evidence",
        ),
        EndpointEvidence(
            EndpointName.COMPLETED,
            "completed" in statuses,
            "deterministic_completion",
            produced,
        ),
        EndpointEvidence(
            EndpointName.SCIENTIFICALLY_VALIDATED,
            False,
            "no_registered_scientific_oracle",
            reason="execution scaffold does not validate a scientific outcome",
        ),
    )
    failure_code = next(
        (
            str(item.get("failure_code"))
            for item in results
            if isinstance(item, Mapping) and item.get("failure_code")
        ),
        None,
    )
    return TrialEndpoints(
        trace.get("episode_id", "unknown"), endpoints, failure_category(failure_code)
    )
