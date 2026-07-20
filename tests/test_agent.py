import sys
from pathlib import Path

from deadman.agent import run_agent_cli
from deadman.store import EvidenceStore


def test_run_agent_cli_returns_child_exit_code(tmp_path: Path) -> None:
    exit_code = run_agent_cli(
        (sys.executable, "-c", "print('agent ok')"),
        workspace=tmp_path,
        hung_timeout_seconds=5.0,
    )

    assert exit_code == 0


def test_run_agent_cli_auto_recovers_hung_child(tmp_path: Path) -> None:
    script = (
        "import subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "raise SystemExit(child.wait())"
    )
    database = tmp_path / "deadman.sqlite"

    exit_code = run_agent_cli(
        (sys.executable, "-c", script),
        workspace=tmp_path,
        database_path=database,
        hung_timeout_seconds=0.2,
        auto_recover=True,
    )

    assert exit_code != 0
    assert EvidenceStore(database).count("signals") == 1
