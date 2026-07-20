"""Deterministic diagnosis fixture client."""

from __future__ import annotations

from deadman.domain import Diagnosis, RecoveryAction, Signal, SignalKind


class FakeDiagnosisClient:
    """Return evidence-bound recommendations for offline replay and tests."""

    def diagnose(self, signal: Signal) -> Diagnosis:
        action = _recommended_action(signal.kind)
        return Diagnosis(
            classification=signal.kind,
            confidence=0.84,
            recommended_action=action,
            rationale=f"{signal.kind.value} matched deterministic replay evidence.",
            evidence_ids=signal.evidence_ids,
            guidance=_guidance(signal.kind),
            requires_human_approval=action
            in {
                RecoveryAction.TERMINATE_DESCENDANT_PROCESS,
                RecoveryAction.CANCEL_AND_RESUME,
                RecoveryAction.CHECKPOINT_AND_RESPAWN,
            },
        )


def _recommended_action(kind: SignalKind) -> RecoveryAction:
    if kind is SignalKind.HUNG_PROCESS:
        return RecoveryAction.TERMINATE_DESCENDANT_PROCESS
    if kind is SignalKind.REPEATED_FAILURE:
        return RecoveryAction.CANCEL_AND_RESUME
    if kind is SignalKind.NO_PROGRESS:
        return RecoveryAction.CANCEL_AND_RESUME
    if kind is SignalKind.SESSION_BUDGET_RISK:
        return RecoveryAction.CHECKPOINT_AND_RESPAWN
    return RecoveryAction.HALT_AND_ESCALATE


def _guidance(kind: SignalKind) -> str:
    if kind is SignalKind.HUNG_PROCESS:
        return (
            "The stuck descendant process was terminated and the parent run recovered. "
            "Do not rerun the same no-output command; continue from verified progress "
            "or summarize that the supervision diagnostic succeeded."
        )
    if kind is SignalKind.REPEATED_FAILURE:
        return "Resume with the repeated failure signature and unchanged workspace evidence."
    if kind is SignalKind.NO_PROGRESS:
        return "Stop repeating completed attempts and resume from the latest unchanged evidence."
    if kind is SignalKind.SESSION_BUDGET_RISK:
        return "Write a checkpoint handoff and respawn a fresh session from verified facts."
    return "Escalate with the captured evidence."
