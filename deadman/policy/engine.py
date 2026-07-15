"""Deterministic policy checks for diagnosis recommendations."""

from __future__ import annotations

from collections.abc import Iterable

from deadman.domain import Diagnosis, PolicyDecision, RecoveryAction, Signal

AUTO_ALLOWED_ACTIONS = frozenset({RecoveryAction.OBSERVE, RecoveryAction.HALT_AND_ESCALATE})


class PolicyEngine:
    """Authorize typed actions without trusting the diagnosis source."""

    def __init__(self, *, auto_recover: bool = False, available_session_id: bool = False) -> None:
        self.auto_recover = auto_recover
        self.available_session_id = available_session_id
        self._used_fingerprints: set[str] = set()

    def evaluate(
        self,
        diagnosis: Diagnosis,
        signal: Signal,
        *,
        action_fingerprint: str,
        known_evidence_ids: Iterable[str],
    ) -> PolicyDecision:
        known = set(known_evidence_ids)
        if diagnosis.classification != signal.kind:
            return _deny(diagnosis.recommended_action, "diagnosis classification mismatch")
        if not set(diagnosis.evidence_ids).issubset(known):
            return _deny(diagnosis.recommended_action, "diagnosis names unknown evidence")
        if not set(diagnosis.evidence_ids).issubset(set(signal.evidence_ids)):
            return _deny(diagnosis.recommended_action, "diagnosis evidence is outside the signal")
        if action_fingerprint in self._used_fingerprints:
            return _deny(diagnosis.recommended_action, "action fingerprint already used")
        if (
            diagnosis.recommended_action is RecoveryAction.CANCEL_AND_RESUME
            and not self.available_session_id
        ):
            return _deny(diagnosis.recommended_action, "cancel and resume requires a session id")
        if diagnosis.recommended_action not in AUTO_ALLOWED_ACTIONS and not self.auto_recover:
            return PolicyDecision(
                allowed=False,
                action=diagnosis.recommended_action,
                reason="human approval required",
            )

        self._used_fingerprints.add(action_fingerprint)
        return PolicyDecision(
            allowed=True,
            action=diagnosis.recommended_action,
            reason="policy approved",
        )


def _deny(action: RecoveryAction, reason: str) -> PolicyDecision:
    return PolicyDecision(allowed=False, action=action, reason=reason)
