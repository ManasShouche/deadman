"""Incident state-machine helpers."""

from __future__ import annotations

from deadman.domain.models import Incident, IncidentState, StateTransition

RECOVERY_ATTEMPT_STATES = frozenset({IncidentState.RECOVERING})
TERMINAL_STATES = frozenset({IncidentState.RESOLVED, IncidentState.ESCALATED})
MAX_RECOVERY_ATTEMPTS = 2


def transition_incident(
    incident: Incident,
    *,
    to_state: IncidentState,
    timestamp: float,
    reason: str,
    actor: str,
    evidence_ids: tuple[str, ...] = (),
    action_fingerprint: str | None = None,
) -> Incident:
    """Move an incident to a valid next state and record the transition."""

    if incident.state in TERMINAL_STATES:
        raise ValueError("cannot transition a terminal incident")
    if to_state not in _ALLOWED_TRANSITIONS[incident.state]:
        raise ValueError(f"invalid transition {incident.state.value} -> {to_state.value}")

    recovery_attempts = incident.recovery_attempts
    if to_state in RECOVERY_ATTEMPT_STATES:
        if recovery_attempts >= MAX_RECOVERY_ATTEMPTS:
            raise ValueError("incident exceeded recovery attempt limit")
        recovery_attempts += 1

    transition = StateTransition(
        from_state=incident.state,
        to_state=to_state,
        timestamp=timestamp,
        reason=reason,
        actor=actor,
        evidence_ids=evidence_ids,
        action_fingerprint=action_fingerprint,
    )
    return incident.model_copy(
        update={
            "state": to_state,
            "transitions": (*incident.transitions, transition),
            "recovery_attempts": recovery_attempts,
        }
    )


_ALLOWED_TRANSITIONS = {
    IncidentState.OPEN: frozenset({IncidentState.DIAGNOSING}),
    IncidentState.DIAGNOSING: frozenset(
        {IncidentState.AWAITING_APPROVAL, IncidentState.RECOVERING, IncidentState.ESCALATED}
    ),
    IncidentState.AWAITING_APPROVAL: frozenset({IncidentState.RECOVERING, IncidentState.ESCALATED}),
    IncidentState.RECOVERING: frozenset({IncidentState.VERIFYING, IncidentState.ESCALATED}),
    IncidentState.VERIFYING: frozenset(
        {IncidentState.RESOLVED, IncidentState.ESCALATED, IncidentState.RECOVERING}
    ),
}
