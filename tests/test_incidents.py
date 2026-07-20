from pathlib import Path

from deadman.diagnosis import FakeDiagnosisClient
from deadman.domain import (
    ActionResult,
    IncidentState,
    PolicyDecision,
    RecoveryAction,
    Severity,
    Signal,
    SignalKind,
    VerificationResult,
)
from deadman.incidents import record_recovery_incident
from deadman.policy import PolicyEngine
from deadman.store import EvidenceStore


def _signal() -> Signal:
    return Signal(
        kind=SignalKind.HUNG_PROCESS,
        severity=Severity.CRITICAL,
        evidence_ids=("proc_1",),
        fingerprint="HUNG_PROCESS:deadbeef",
        details={"pid": 4321, "root_pid": 1234},
    )


def _terminated_action() -> ActionResult:
    return ActionResult(
        action=RecoveryAction.TERMINATE_DESCENDANT_PROCESS,
        attempted=True,
        succeeded=True,
        evidence_ids=("proc_1",),
        message="terminated descendant process",
    )


def test_record_recovery_incident_resolves_on_verified_recovery(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "deadman.sqlite")
    signal = _signal()
    diagnosis = FakeDiagnosisClient().diagnose(signal)
    policy = PolicyEngine(auto_recover=True).evaluate(
        diagnosis,
        signal,
        action_fingerprint=f"action:{signal.fingerprint}",
        known_evidence_ids=signal.evidence_ids,
    )
    verification = VerificationResult(
        resolved=True,
        changed_progress_fingerprint=True,
        success_signal="child gone",
        reason="verified",
    )

    incident = record_recovery_incident(
        store,
        session_id="session-1",
        signal=signal,
        diagnosis=diagnosis,
        policy=policy,
        action_result=_terminated_action(),
        verification=verification,
        report="report body",
    )

    assert incident is not None
    assert incident.state is IncidentState.RESOLVED
    assert store.count("incidents") == 1
    assert store.count("diagnoses") == 1
    assert store.count("action_results") == 1
    assert store.count("verification_results") == 1
    assert store.count("reports") == 1


def test_record_recovery_incident_awaits_approval_when_policy_blocks(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "deadman.sqlite")
    signal = _signal()
    diagnosis = FakeDiagnosisClient().diagnose(signal)
    policy = PolicyEngine(auto_recover=False).evaluate(
        diagnosis,
        signal,
        action_fingerprint=f"action:{signal.fingerprint}",
        known_evidence_ids=signal.evidence_ids,
    )
    assert not policy.allowed

    incident = record_recovery_incident(
        store,
        session_id="session-1",
        signal=signal,
        diagnosis=diagnosis,
        policy=policy,
        action_result=None,
        verification=None,
        report="awaiting approval",
    )

    assert incident is not None
    assert incident.state is IncidentState.AWAITING_APPROVAL
    assert store.count("action_results") == 0


def test_record_recovery_incident_escalates_on_failed_verification(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "deadman.sqlite")
    signal = _signal()
    diagnosis = FakeDiagnosisClient().diagnose(signal)
    policy = PolicyDecision(
        allowed=True,
        action=RecoveryAction.TERMINATE_DESCENDANT_PROCESS,
        reason="policy approved",
    )
    verification = VerificationResult(
        resolved=False,
        changed_progress_fingerprint=False,
        success_signal=None,
        reason="still present",
    )

    incident = record_recovery_incident(
        store,
        session_id="session-1",
        signal=signal,
        diagnosis=diagnosis,
        policy=policy,
        action_result=_terminated_action(),
        verification=verification,
        report="escalated",
    )

    assert incident is not None
    assert incident.state is IncidentState.ESCALATED


def test_record_recovery_incident_skips_without_diagnosis(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "deadman.sqlite")
    incident = record_recovery_incident(
        store,
        session_id="session-1",
        signal=_signal(),
        diagnosis=None,
        policy=None,
        action_result=None,
        verification=None,
        report="",
    )
    assert incident is None
    assert store.count("incidents") == 0
