import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from deadman.domain import RecoveryAction
from deadman.executor import terminate_descendant_process, write_checkpoint_handoff


def test_terminate_descendant_process_rejects_protected_pid() -> None:
    result = terminate_descendant_process(
        root_pid=os.getpid(),
        target_pid=os.getpid(),
        evidence_id="proc_self",
    )

    assert result.attempted is False
    assert result.succeeded is False
    assert "protected pid" in result.message


def test_terminate_descendant_process_rejects_unowned_pid() -> None:
    result = terminate_descendant_process(
        root_pid=999_999,
        target_pid=os.getpid(),
        evidence_id="proc_unowned",
    )

    assert result.attempted is False
    assert result.succeeded is False


def test_terminate_descendant_process_stops_owned_child() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        result = terminate_descendant_process(
            root_pid=os.getpid(),
            target_pid=child.pid,
            evidence_id="proc_child",
            terminate_timeout_seconds=1.0,
        )

        assert result.attempted is True
        assert result.succeeded is True
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


def test_terminate_descendant_process_rejects_orphaned_setsid_grandchild() -> None:
    launcher = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import subprocess, sys; "
                "child = subprocess.Popen("
                "[sys.executable, '-c', 'import time; time.sleep(30)'], "
                "start_new_session=True"
                "); "
                "print(child.pid, flush=True)"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert launcher.stdout is not None
    target_pid = int(launcher.stdout.readline().strip())
    launcher.wait(timeout=10)
    time.sleep(0.1)

    try:
        result = terminate_descendant_process(
            root_pid=os.getpid(),
            target_pid=target_pid,
            evidence_id="proc_orphaned_setsid",
            terminate_timeout_seconds=1.0,
        )

        assert result.attempted is False
        assert result.succeeded is False
        assert "not a proven descendant" in result.message
    finally:
        try:
            os.kill(target_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_write_checkpoint_handoff_stays_under_deadman_directory(tmp_path: Path) -> None:
    result = write_checkpoint_handoff(
        workspace=tmp_path,
        incident_id="../incident 1",
        guidance="Use verified facts only.",
        original_task="Fix the test.",
    )

    assert result.action == RecoveryAction.CHECKPOINT_AND_RESPAWN
    assert result.succeeded is True
    assert result.artifact_path is not None
    handoff_path = Path(result.artifact_path)
    assert handoff_path.parent == tmp_path / ".deadman" / "handoffs"
    assert handoff_path.name == "incident-1.md"
    assert "Use verified facts only." in handoff_path.read_text(encoding="utf-8")
