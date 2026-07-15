import json
from pathlib import Path

import pytest

from deadman.adapter import parse_jsonl_lines
from deadman.domain import ProcessObservation, Severity, Signal, SignalKind
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
