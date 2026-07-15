from pathlib import Path

from deadman.detectors.replay import replay_fixture
from deadman.domain import RecoveryAction, SignalKind
from deadman.report import render_incident_report


def test_replay_pipeline_resolves_hung_process_fixture() -> None:
    incident = replay_fixture(Path("scenarios/recordings/hung-process.jsonl"))

    assert incident is not None
    assert incident.signal.kind == SignalKind.HUNG_PROCESS
    assert incident.diagnosis.recommended_action == RecoveryAction.TERMINATE_DESCENDANT_PROCESS
    assert incident.policy.allowed is True
    assert incident.verification.resolved is True


def test_replay_pipeline_resolves_repeated_failure_fixture() -> None:
    incident = replay_fixture(Path("scenarios/recordings/repeated-failure.jsonl"))

    assert incident is not None
    assert incident.signal.kind == SignalKind.REPEATED_FAILURE
    assert incident.diagnosis.recommended_action == RecoveryAction.CANCEL_AND_RESUME
    assert incident.policy.allowed is True
    assert incident.verification.resolved is True


def test_replay_pipeline_resolves_session_handoff_fixture() -> None:
    incident = replay_fixture(Path("scenarios/recordings/session-handoff.jsonl"))

    assert incident is not None
    assert incident.signal.kind == SignalKind.SESSION_BUDGET_RISK
    assert incident.diagnosis.recommended_action == RecoveryAction.CHECKPOINT_AND_RESPAWN
    assert incident.policy.allowed is True
    assert incident.verification.resolved is True


def test_render_incident_report_contains_key_fields() -> None:
    incident = replay_fixture(Path("scenarios/recordings/repeated-failure.jsonl"))

    assert incident is not None
    report = render_incident_report(incident)

    assert "Incident: repeated-failure" in report
    assert "Signal: REPEATED_FAILURE" in report
    assert "Recommended action: CANCEL_AND_RESUME" in report
    assert "Verification: resolved" in report
