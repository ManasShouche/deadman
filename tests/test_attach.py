import os
import subprocess
import sys
import time
from pathlib import Path

from deadman.attach import (
    LiveCodexProcess,
    _drop_nested_candidates,
    _looks_like_codex,
    _within_repo,
    discover_live_codex_processes,
    run_attach_supervisor,
)
from deadman.diagnosis import FakeDiagnosisClient
from deadman.domain import IncidentState
from deadman.store import EvidenceStore


def test_within_repo_matches_root_and_subdirectories(tmp_path: Path) -> None:
    repo = tmp_path.resolve()
    nested = repo / "a" / "b"
    assert _within_repo(repo, repo)
    assert _within_repo(nested, repo)
    assert not _within_repo(tmp_path.parent, repo)


def test_looks_like_codex_matches_binary_and_argv() -> None:
    assert _looks_like_codex("codex", ["/opt/homebrew/bin/codex", "resume"])
    assert _looks_like_codex(None, ["/opt/homebrew/bin/codex", "--sandbox", "workspace-write"])
    assert _looks_like_codex(None, ["node", "/path/codex", "exec"])
    assert not _looks_like_codex("python3.11", ["python", "-c", "print(1)"])
    assert not _looks_like_codex(None, [])


def test_discover_ignores_excluded_and_non_codex_processes(tmp_path: Path) -> None:
    # This test process is python, not codex, so discovery must return nothing.
    found = discover_live_codex_processes(
        tmp_path,
        exclude_pids=frozenset({os.getpid()}),
    )
    assert all(process.pid != os.getpid() for process in found)


def test_live_codex_process_label_prefers_session_id() -> None:
    linked = LiveCodexProcess(
        pid=10,
        cwd=Path("/repo"),
        command_line=("codex",),
        create_time=0.0,
        session_id="abc",
    )
    unlinked = LiveCodexProcess(
        pid=11,
        cwd=Path("/repo"),
        command_line=("codex",),
        create_time=0.0,
        session_id=None,
    )
    assert linked.label == "abc"
    assert unlinked.label == "pid:11"


def test_drop_nested_candidates_keeps_top_most_ancestor(tmp_path: Path) -> None:
    # A parent process that spawns a child mirrors `node <path>/codex` -> `codex`.
    child_pid_file = tmp_path / "child.pid"
    inner = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    root_script = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {inner!r}]); "
        "time.sleep(30)"
    )
    root = subprocess.Popen([sys.executable, "-c", root_script])
    try:
        _wait_for(child_pid_file.exists, timeout=5.0)
        child_pid = int(child_pid_file.read_text())
        parent = LiveCodexProcess(
            pid=root.pid,
            cwd=tmp_path,
            command_line=("node", "codex"),
            create_time=1.0,
            session_id=None,
        )
        child = LiveCodexProcess(
            pid=child_pid,
            cwd=tmp_path,
            command_line=("codex",),
            create_time=2.0,
            session_id=None,
        )

        kept = _drop_nested_candidates([child, parent])

        assert [process.pid for process in kept] == [root.pid]
    finally:
        _terminate(root)


def test_attach_supervisor_recovers_externally_launched_hung_child(tmp_path: Path) -> None:
    grandchild_pid_file = tmp_path / "grandchild.pid"
    inner_script = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(grandchild_pid_file)!r}).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    root_script = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {inner_script!r}]); "
        "time.sleep(30)"
    )
    root = subprocess.Popen([sys.executable, "-c", root_script])
    try:
        _wait_for(lambda: grandchild_pid_file.exists(), timeout=5.0)
        grandchild_pid = int(grandchild_pid_file.read_text())
        process = LiveCodexProcess(
            pid=root.pid,
            cwd=tmp_path.resolve(),
            command_line=("codex", "exec"),
            create_time=0.0,
            session_id=None,
        )
        database = tmp_path / "deadman.sqlite"

        incidents = run_attach_supervisor(
            process,
            workspace=tmp_path,
            database_path=database,
            diagnosis_client=FakeDiagnosisClient(),
            hung_timeout_seconds=0.2,
            auto_recover=True,
            poll_interval_seconds=0.05,
            max_polls=80,
        )

        assert incidents >= 1
        store = EvidenceStore(database)
        assert store.count("signals") >= 1
        assert store.count("incidents") >= 1
        assert store.count("action_results") >= 1
        assert store.count("sessions") >= 1
        states = {payload["state"] for payload in store.list_payloads("incidents")}
        assert IncidentState.RESOLVED.value in states
        time.sleep(0.2)
        # The fake root never reaps, so the killed child lingers as a zombie;
        # a zombie is terminated, not a live hung descendant.
        assert not _is_live_process(grandchild_pid)
    finally:
        _terminate(root)


def test_attach_supervisor_awaits_approval_without_auto_recover(tmp_path: Path) -> None:
    grandchild_pid_file = tmp_path / "grandchild.pid"
    inner_script = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(grandchild_pid_file)!r}).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    root_script = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {inner_script!r}]); "
        "time.sleep(30)"
    )
    root = subprocess.Popen([sys.executable, "-c", root_script])
    try:
        _wait_for(lambda: grandchild_pid_file.exists(), timeout=5.0)
        grandchild_pid = int(grandchild_pid_file.read_text())
        process = LiveCodexProcess(
            pid=root.pid,
            cwd=tmp_path.resolve(),
            command_line=("codex", "exec"),
            create_time=0.0,
            session_id=None,
        )
        database = tmp_path / "deadman.sqlite"

        incidents = run_attach_supervisor(
            process,
            workspace=tmp_path,
            database_path=database,
            diagnosis_client=FakeDiagnosisClient(),
            hung_timeout_seconds=0.2,
            auto_recover=False,
            poll_interval_seconds=0.05,
            max_polls=80,
        )

        assert incidents >= 1
        store = EvidenceStore(database)
        assert store.count("action_results") == 0
        states = {payload["state"] for payload in store.list_payloads("incidents")}
        assert IncidentState.AWAITING_APPROVAL.value in states
        # Approval mode must not kill the hung child.
        assert _is_live_process(grandchild_pid)
    finally:
        _terminate(root)


def _wait_for(predicate, *, timeout: float) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met before timeout")


def _is_live_process(pid: int) -> bool:
    """Return True only for a running, non-zombie process."""

    import psutil

    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def _terminate(process: subprocess.Popen) -> None:  # type: ignore[type-arg]
    process.terminate()
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3.0)
