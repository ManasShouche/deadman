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
