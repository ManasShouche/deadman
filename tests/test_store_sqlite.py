import json
import sqlite3
from pathlib import Path

import pytest

from deadman.adapter import parse_jsonl_lines
from deadman.domain import (
    ActionResult,
    Diagnosis,
    Incident,
    IncidentState,
    ProcessObservation,
    RecoveryAction,
    Severity,
    Signal,
    SignalKind,
    VerificationResult,
)
from deadman.domain.incident import transition_incident
from deadman.store import EvidenceStore


def test_evidence_store_persists_adapter_records(tmp_path: Path) -> None:
    parsed = parse_jsonl_lines(
        [
            json.dumps({"type": "thread.started", "thread_id": "session-123"}),
            "{broken",
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1}}),
        ]
    )
    store = EvidenceStore(tmp_path / "deadman.sqlite")

    store.add_raw_events(parsed.raw_events)
    store.add_normalized_events(parsed.normalized_events)
    report_id = store.add_capability_report(parsed.capabilities)

    assert report_id == 1
    assert store.count("raw_events") == 3
    assert store.count("normalized_events") == 2
    assert store.list_payloads("capability_reports")[0]["persisted_session_id"] == "session-123"


def test_evidence_store_persists_process_observations_and_signals(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "deadman.sqlite")
    observation = ProcessObservation(
        evidence_id="proc_1",
        root_pid=100,
        pid=101,
        parent_pid=100,
        command_line=("sleep", "999"),
        is_running=True,
        is_descendant=True,
        observed_at=120.0,
        last_stdout_at=1.0,
    )
    signal = Signal(
        kind=SignalKind.HUNG_PROCESS,
        severity=Severity.CRITICAL,
        evidence_ids=("proc_1",),
        fingerprint="hung:101",
        details={"pid": 101},
    )

    store.add_process_observations([observation])
    store.add_signals([signal])

    assert store.list_payloads("process_observations")[0]["pid"] == 101
    assert store.list_payloads("signals")[0]["kind"] == "HUNG_PROCESS"


def test_evidence_store_rejects_unknown_tables(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "deadman.sqlite")

    with pytest.raises(ValueError, match="unsupported table"):
        store.count("not_a_table")

    with pytest.raises(ValueError, match="unsupported payload table"):
        store.list_payloads("raw_events")


def test_evidence_store_persists_incident_lifecycle_records(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "deadman.sqlite")
    signal = Signal(
        kind=SignalKind.HUNG_PROCESS,
        severity=Severity.CRITICAL,
        evidence_ids=("proc_1",),
        fingerprint="hung:101",
    )
    incident = Incident(incident_id="inc_1", state=IncidentState.OPEN, signal=signal)
    incident = transition_incident(
        incident,
        to_state=IncidentState.DIAGNOSING,
        timestamp=1.0,
        reason="signal opened",
        actor="deterministic-supervisor",
        evidence_ids=("proc_1",),
    )
    diagnosis = Diagnosis(
        classification=SignalKind.HUNG_PROCESS,
        confidence=0.9,
        recommended_action=RecoveryAction.TERMINATE_DESCENDANT_PROCESS,
        rationale="idle owned child",
        evidence_ids=("proc_1",),
        guidance="terminate child",
        requires_human_approval=True,
    )
    action = ActionResult(
        action=RecoveryAction.TERMINATE_DESCENDANT_PROCESS,
        attempted=True,
        succeeded=True,
        evidence_ids=("proc_1",),
        message="terminated",
    )
    verification = VerificationResult(
        resolved=True,
        changed_progress_fingerprint=True,
        success_signal="parent progressed",
        reason="verified",
    )

    store.add_incident(incident)
    store.add_transitions(incident.incident_id, incident.transitions)
    store.add_diagnosis(incident.incident_id, diagnosis)
    store.add_action_result(incident.incident_id, action)
    store.add_verification_result(incident.incident_id, verification)
    store.add_report(incident.incident_id, "incident report")

    assert store.list_payloads("incidents")[0]["incident_id"] == "inc_1"
    assert store.list_payloads("transitions")[0]["to_state"] == "DIAGNOSING"
    assert (
        store.list_payloads("diagnoses")[0]["recommended_action"]
        == "TERMINATE_DESCENDANT_PROCESS"
    )
    assert store.list_payloads("action_results")[0]["succeeded"] is True
    assert store.list_payloads("verification_results")[0]["resolved"] is True
    assert store.list_payloads("reports")[0]["report"] == "incident report"


def test_evidence_store_migrates_legacy_raw_events_without_deleting_them(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            create table raw_events (
                id text primary key,
                line_number integer not null,
                event_type text not null,
                raw_line text not null,
                parse_error text,
                payload_json text
            )
            """
        )
        connection.execute(
            """
            insert into raw_events values
            ('evt_1', 1, 'thread.started', '{"type":"thread.started"}', null,
             '{"type":"thread.started"}')
            """
        )

    store = EvidenceStore(path)

    assert store.count("raw_events") == 1
    assert store.get_session("legacy-unscoped") is not None
    assert store.session_event_count("legacy-unscoped") == 1
