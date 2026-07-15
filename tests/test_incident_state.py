import pytest

from deadman.domain import Incident, IncidentState, Severity, Signal, SignalKind
from deadman.domain.incident import transition_incident


def _incident() -> Incident:
    return Incident(
        incident_id="inc_1",
        state=IncidentState.OPEN,
        signal=Signal(
            kind=SignalKind.HUNG_PROCESS,
            severity=Severity.CRITICAL,
            evidence_ids=("proc_001",),
            fingerprint="hung:1",
        ),
    )


def test_transition_incident_records_auditable_transition() -> None:
    incident = transition_incident(
        _incident(),
        to_state=IncidentState.DIAGNOSING,
        timestamp=1.0,
        reason="signal opened",
        actor="deterministic-supervisor",
        evidence_ids=("proc_001",),
    )

    assert incident.state == IncidentState.DIAGNOSING
    assert incident.transitions[0].from_state == IncidentState.OPEN
    assert incident.transitions[0].to_state == IncidentState.DIAGNOSING
    assert incident.transitions[0].evidence_ids == ("proc_001",)


def test_transition_incident_rejects_invalid_transition() -> None:
    with pytest.raises(ValueError, match="invalid transition"):
        transition_incident(
            _incident(),
            to_state=IncidentState.RESOLVED,
            timestamp=1.0,
            reason="skip",
            actor="test",
        )


def test_transition_incident_caps_recovery_attempts_at_two() -> None:
    incident = _incident()
    incident = transition_incident(
        incident,
        to_state=IncidentState.DIAGNOSING,
        timestamp=1.0,
        reason="diagnose",
        actor="test",
    )
    incident = transition_incident(
        incident,
        to_state=IncidentState.RECOVERING,
        timestamp=2.0,
        reason="first",
        actor="test",
    )
    incident = transition_incident(
        incident,
        to_state=IncidentState.VERIFYING,
        timestamp=3.0,
        reason="verify",
        actor="test",
    )
    incident = transition_incident(
        incident,
        to_state=IncidentState.RECOVERING,
        timestamp=4.0,
        reason="second",
        actor="test",
    )
    incident = transition_incident(
        incident,
        to_state=IncidentState.VERIFYING,
        timestamp=5.0,
        reason="verify again",
        actor="test",
    )

    with pytest.raises(ValueError, match="recovery attempt limit"):
        transition_incident(
            incident,
            to_state=IncidentState.RECOVERING,
            timestamp=6.0,
            reason="third",
            actor="test",
        )
