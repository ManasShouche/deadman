import sys
from pathlib import Path

from deadman.run import run_supervised_command
from deadman.store import EvidenceStore


def test_run_supervised_command_persists_completed_jsonl_run(tmp_path: Path) -> None:
    script = (
        "import json; "
        "print(json.dumps({'type':'thread.started','thread_id':'s1'})); "
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message'}}))"
    )
    db_path = tmp_path / ".deadman" / "deadman.sqlite"

    summary = run_supervised_command(
        (sys.executable, "-c", script),
        workspace=tmp_path,
        database_path=db_path,
    )

    store = EvidenceStore(db_path)
    assert summary.status == "completed"
    assert summary.session_id == "s1"
    assert summary.raw_event_count == 2
    assert store.count("raw_events") == 2
    assert store.count("capability_reports") == 1


def test_run_supervised_command_reports_nonzero_run(tmp_path: Path) -> None:
    script = "import sys; sys.exit(7)"

    summary = run_supervised_command((sys.executable, "-c", script), workspace=tmp_path)

    assert summary.returncode == 7
    assert summary.status == "exited_nonzero"
    assert "Return code: 7" in summary.report


def test_run_supervised_command_recovers_hung_descendant(tmp_path: Path) -> None:
    script = (
        "import json, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "child.wait(); "
        "print(json.dumps({'type':'thread.started','thread_id':'live'})); "
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message'}}))"
    )
    db_path = tmp_path / ".deadman" / "deadman.sqlite"

    summary = run_supervised_command(
        (sys.executable, "-c", script),
        workspace=tmp_path,
        database_path=db_path,
        auto_recover=True,
        hung_timeout_seconds=0.2,
    )

    store = EvidenceStore(db_path)
    assert summary.status == "recovered"
    assert summary.returncode == 0
    assert summary.signal_kind is not None
    assert summary.signal_kind.value == "HUNG_PROCESS"
    assert summary.recommended_action is not None
    assert summary.recommended_action.value == "TERMINATE_DESCENDANT_PROCESS"
    assert summary.policy_allowed is True
    assert summary.verification_resolved is True
    assert summary.session_id == "live"
    assert store.count("process_observations") >= 1
    assert store.count("signals") == 1


def test_run_supervised_command_blocks_live_recovery_without_auto_recover(
    tmp_path: Path,
) -> None:
    script = (
        "import subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "child.wait()"
    )

    summary = run_supervised_command(
        (sys.executable, "-c", script),
        workspace=tmp_path,
        auto_recover=False,
        hung_timeout_seconds=0.2,
    )

    assert summary.status == "awaiting_approval"
    assert summary.policy_allowed is False
    assert summary.verification_resolved is False
    assert "human approval required" in summary.report
