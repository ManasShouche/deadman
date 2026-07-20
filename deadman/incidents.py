"""Shared incident lifecycle recording for every live recovery path.

Managed (`deadman run`), interactive (`deadman agent`), and attach
(`deadman attach`) supervision all reach the same deterministic incident
state machine through this module so a recovery is always auditable:
signal -> diagnosis -> policy -> action -> verification -> report.
"""

from __future__ import annotations

import time

from deadman.domain import (
    ActionResult,
    Diagnosis,
    Incident,
    IncidentState,
    PolicyDecision,
    Signal,
    VerificationResult,
)
from deadman.domain.incident import transition_incident
from deadman.store import EvidenceStore


def incident_id_for(signal: Signal) -> str:
    """Return the stable incident id derived from a signal fingerprint."""

    suffix = signal.fingerprint.split(":", maxsplit=1)[-1]
    return f"live-{signal.kind.value.lower()}-{suffix}"


def record_recovery_incident(
    store: EvidenceStore,
    *,
    session_id: str,
    signal: Signal | None,
    diagnosis: Diagnosis | None,
    policy: PolicyDecision | None,
    action_result: ActionResult | None,
    verification: VerificationResult | None,
    report: str,
    final_resolved: bool | None = None,
    incident_id: str | None = None,
    timestamp: float | None = None,
) -> Incident | None:
    """Build and persist one incident through the deterministic state machine.

    ``final_resolved`` overrides ``verification.resolved`` when a caller has
    additional post-action evidence (for example a follow-up resume). It
    defaults to ``verification.resolved``.
    """

    if signal is None or diagnosis is None or policy is None:
        return None

    incident = build_recovery_incident(
        signal=signal,
        policy=policy,
        action_result=action_result,
        verification=verification,
        final_resolved=final_resolved,
        incident_id=incident_id,
        timestamp=timestamp,
    )

    store.add_incident(incident, session_id=session_id)
    store.add_transitions(incident.incident_id, incident.transitions)
    store.add_canonical_transitions(
        incident,
        policy=policy,
        action_result=action_result,
    )
    store.add_diagnosis(incident.incident_id, diagnosis)
    store.add_policy_decision(incident.incident_id, policy)
    if action_result is not None:
        store.add_action_result(incident.incident_id, action_result)
    if verification is not None:
        store.add_verification_result(incident.incident_id, verification)
    store.add_report(incident.incident_id, report)
    return incident


def build_recovery_incident(
    *,
    signal: Signal,
    policy: PolicyDecision,
    action_result: ActionResult | None,
    verification: VerificationResult | None,
    final_resolved: bool | None = None,
    incident_id: str | None = None,
    timestamp: float | None = None,
) -> Incident:
    """Drive the incident state machine from a diagnosed signal to a terminal state."""

    stamp = time.time() if timestamp is None else timestamp

    incident = Incident(
        incident_id=incident_id or incident_id_for(signal),
        state=IncidentState.OPEN,
        signal=signal,
    )
    incident = transition_incident(
        incident,
        to_state=IncidentState.DIAGNOSING,
        timestamp=stamp,
        reason="deterministic signal opened incident",
        actor="deadman-supervisor",
        evidence_ids=signal.evidence_ids,
    )

    if not policy.allowed:
        return transition_incident(
            incident,
            to_state=IncidentState.AWAITING_APPROVAL,
            timestamp=stamp,
            reason=policy.reason,
            actor="policy-engine",
            evidence_ids=signal.evidence_ids,
        )

    if action_result is None:
        return transition_incident(
            incident,
            to_state=IncidentState.ESCALATED,
            timestamp=stamp,
            reason="no supported live action was executed",
            actor="deadman-supervisor",
            evidence_ids=signal.evidence_ids,
        )

    incident = transition_incident(
        incident,
        to_state=IncidentState.RECOVERING,
        timestamp=stamp,
        reason="policy authorized bounded action",
        actor="policy-engine",
        evidence_ids=action_result.evidence_ids,
        action_fingerprint=f"action:{signal.fingerprint}",
    )

    if verification is None:
        return transition_incident(
            incident,
            to_state=IncidentState.ESCALATED,
            timestamp=stamp,
            reason="recovery produced no verification evidence",
            actor="deterministic-verifier",
            evidence_ids=action_result.evidence_ids,
        )

    incident = transition_incident(
        incident,
        to_state=IncidentState.VERIFYING,
        timestamp=stamp,
        reason="bounded action completed",
        actor="deadman-supervisor",
        evidence_ids=action_result.evidence_ids,
    )
    resolved = verification.resolved if final_resolved is None else final_resolved
    return transition_incident(
        incident,
        to_state=IncidentState.RESOLVED if resolved else IncidentState.ESCALATED,
        timestamp=stamp,
        reason=(
            "measurable progress verified"
            if resolved
            else "verification evidence was insufficient"
        ),
        actor="deterministic-verifier",
        evidence_ids=action_result.evidence_ids,
    )
