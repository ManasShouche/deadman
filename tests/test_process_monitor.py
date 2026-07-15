import os
import subprocess
import sys
import time

from deadman.monitor import ProcessMonitor


def test_process_monitor_observes_owned_child_process() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        monitor = ProcessMonitor(os.getpid())
        observation = monitor.observe(
            child.pid,
            evidence_id="proc_child",
            observed_at=time.monotonic(),
            last_stdout_at=1.0,
        )

        assert observation.evidence_id == "proc_child"
        assert observation.pid == child.pid
        assert observation.root_pid == os.getpid()
        assert observation.is_running is True
        assert observation.is_descendant is True
    finally:
        child.terminate()
        child.wait(timeout=10)


def test_process_monitor_rejects_protected_root_pid() -> None:
    try:
        ProcessMonitor(1)
    except ValueError as exc:
        assert "protected root pid" in str(exc)
    else:
        raise AssertionError("expected protected pid rejection")
