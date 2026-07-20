from deadman.diagnosis import FakeDiagnosisClient
from deadman.domain import Diagnosis, RecoveryAction, Severity, Signal, SignalKind
from deadman.policy import PolicyEngine


def _signal() -> Signal:
    return Signal(
        kind=SignalKind.HUNG_PROCESS,
        severity=Severity.CRITICAL,
        evidence_ids=("proc_001",),
        fingerprint="hung:1",
    )


def test_fake_diagnosis_is_evidence_bound_to_signal() -> None:
    signal = _signal()
    diagnosis = FakeDiagnosisClient().diagnose(signal)

    assert diagnosis.classification == SignalKind.HUNG_PROCESS
    assert diagnosis.recommended_action == RecoveryAction.TERMINATE_DESCENDANT_PROCESS
    assert diagnosis.evidence_ids == ("proc_001",)
    assert diagnosis.requires_human_approval is True


def test_policy_requires_approval_for_process_action_by_default() -> None:
    signal = _signal()
    diagnosis = FakeDiagnosisClient().diagnose(signal)

    decision = PolicyEngine().evaluate(
        diagnosis,
        signal,
        action_fingerprint="act:1",
        known_evidence_ids=signal.evidence_ids,
    )

    assert decision.allowed is False
    assert decision.reason == "human approval required"


def test_policy_allows_auto_recover_once_and_rejects_reuse() -> None:
    signal = _signal()
    diagnosis = FakeDiagnosisClient().diagnose(signal)
    policy = PolicyEngine(auto_recover=True)

    first = policy.evaluate(
        diagnosis,
        signal,
        action_fingerprint="act:1",
        known_evidence_ids=signal.evidence_ids,
    )
    second = policy.evaluate(
        diagnosis,
        signal,
        action_fingerprint="act:1",
        known_evidence_ids=signal.evidence_ids,
    )

    assert first.allowed is True
    assert second.allowed is False
    assert second.reason == "action fingerprint already used"


def test_policy_rejects_unknown_evidence_and_missing_session_id() -> None:
    signal = _signal()
    unknown = Diagnosis(
        classification=SignalKind.HUNG_PROCESS,
        confidence=0.8,
        recommended_action=RecoveryAction.TERMINATE_DESCENDANT_PROCESS,
        rationale="bad evidence",
        evidence_ids=("event-999",),
        guidance="none",
        requires_human_approval=True,
    )
    resume = Diagnosis(
        classification=SignalKind.HUNG_PROCESS,
        confidence=0.8,
        recommended_action=RecoveryAction.CANCEL_AND_RESUME,
        rationale="resume",
        evidence_ids=signal.evidence_ids,
        guidance="resume",
        requires_human_approval=True,
    )

    assert (
        PolicyEngine(auto_recover=True)
        .evaluate(
            unknown,
            signal,
            action_fingerprint="act:2",
            known_evidence_ids=signal.evidence_ids,
        )
        .reason
        == "diagnosis names unknown evidence"
    )
    assert (
        PolicyEngine(auto_recover=True)
        .evaluate(
            resume,
            signal,
            action_fingerprint="act:3",
            known_evidence_ids=signal.evidence_ids,
        )
        .reason
        == "cancel and resume requires a session id"
    )
