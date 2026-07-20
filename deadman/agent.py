"""PTY wrapper for supervising the interactive Codex CLI."""

from __future__ import annotations

import os
import pty
import select
import shutil
import signal as signal_module
import sys
import termios
import time
import tty
from collections.abc import Sequence
from pathlib import Path

import psutil

from deadman.detectors import detect_hung_process
from deadman.domain import DetectorConfig, ProcessObservation, Signal
from deadman.executor import terminate_descendant_process
from deadman.paths import default_database_path, project_root
from deadman.store import EvidenceStore

PROCESS_LOOKUP_ERRORS = (
    psutil.NoSuchProcess,
    psutil.AccessDenied,
    psutil.ZombieProcess,
    PermissionError,
)
STATUS_INTERVAL_SECONDS = 10.0


def run_agent_cli(
    argv: Sequence[str],
    *,
    workspace: Path,
    database_path: Path | None = None,
    hung_timeout_seconds: float = 60.0,
    auto_recover: bool = False,
) -> int:
    """Run an interactive CLI in a PTY while supervising its process tree."""

    if not argv:
        raise ValueError("argv must not be empty")

    root = project_root(workspace)
    db_path = database_path or default_database_path(root)
    store = EvidenceStore(db_path)
    columns, rows = _terminal_size()
    child_pid, master_fd = pty.fork()
    if child_pid == 0:
        os.environ["COLUMNS"] = str(columns)
        os.environ["LINES"] = str(rows)
        _set_window_size(0, columns=columns, rows=rows)
        os.execvp(argv[0], list(argv))

    _set_window_size(master_fd, columns=columns, rows=rows)
    stdin_fd = _fileno_or_none(sys.stdin)
    stdout_fd = _fileno_or_none(sys.stdout)
    old_tty = None
    old_sigwinch = signal_module.getsignal(signal_module.SIGWINCH)
    signal_module.signal(
        signal_module.SIGWINCH,
        lambda _signum, _frame: _resize_child_pty(master_fd),
    )
    if stdin_fd is not None and sys.stdin.isatty():
        old_tty = termios.tcgetattr(stdin_fd)
        tty.setraw(stdin_fd)

    last_output_at = time.monotonic()
    first_seen_by_pid: dict[int, float] = {}
    ignored_pids: set[int] = set()
    last_status_at = 0.0
    observations: list[ProcessObservation] = []
    recovered_fingerprints: set[str] = set()

    try:
        while True:
            now = time.monotonic()
            exit_code = _poll_exit_code(child_pid)
            if exit_code is not None:
                _drain_master(master_fd, stdout_fd)
                return exit_code

            readable_fds = [master_fd]
            if stdin_fd is not None and sys.stdin.isatty():
                readable_fds.append(stdin_fd)
            readable, _, _ = select.select(readable_fds, (), (), 0.1)

            if master_fd in readable:
                try:
                    output = os.read(master_fd, 4096)
                except OSError:
                    return _wait_exit_code(child_pid)
                if output:
                    _write_output(stdout_fd, output)
                    last_output_at = now

            if stdin_fd is not None and stdin_fd in readable:
                user_input = os.read(stdin_fd, 4096)
                if user_input:
                    os.write(master_fd, user_input)

            signal = _detect_hung_descendant(
                root_pid=child_pid,
                now=now,
                last_output_at=last_output_at,
                timeout_seconds=hung_timeout_seconds,
                observations=observations,
                first_seen_by_pid=first_seen_by_pid,
                ignored_pids=ignored_pids,
            )
            if now - last_status_at >= STATUS_INTERVAL_SECONDS:
                _persist_recent_observations(store, observations)
                watched_count = len(
                    {
                        observation.pid
                        for observation in observations[-len(first_seen_by_pid) :]
                        if observation.is_descendant and observation.pid not in ignored_pids
                    }
                )
                _write_status(
                    f"\n[deadman] monitoring {watched_count} owned descendant(s); "
                    f"ignored baseline={len(ignored_pids)}\n"
                )
                last_status_at = now
            if signal is None or signal.fingerprint in recovered_fingerprints:
                continue

            _persist_recent_observations(store, observations)
            store.add_signals((signal,))
            recovered_fingerprints.add(signal.fingerprint)
            _write_status(
                f"\n[deadman] HUNG_PROCESS detected for pid {signal.details['pid']}\n"
            )
            if not auto_recover:
                _write_status("[deadman] auto recovery disabled; leaving session running\n")
                continue

            result = terminate_descendant_process(
                root_pid=child_pid,
                target_pid=int(signal.details["pid"]),
                evidence_id=signal.evidence_ids[0],
            )
            store.add_action_result(signal.fingerprint, result)
            _write_status(f"[deadman] {result.message}\n")
            last_output_at = time.monotonic()
    finally:
        signal_module.signal(signal_module.SIGWINCH, old_sigwinch)
        if old_tty is not None and stdin_fd is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_tty)
        try:
            os.close(master_fd)
        except OSError:
            pass


def _detect_hung_descendant(
    *,
    root_pid: int,
    now: float,
    last_output_at: float,
    timeout_seconds: float,
    observations: list[ProcessObservation],
    first_seen_by_pid: dict[int, float],
    ignored_pids: set[int],
) -> Signal | None:
    descendants = _live_descendant_pids(root_pid)
    eligible_observations: list[ProcessObservation] = []
    for pid in descendants:
        first_seen_at = first_seen_by_pid.setdefault(pid, now)
        observation = _observe_descendant(
            root_pid=root_pid,
            pid=pid,
            observed_at=now,
            first_seen_at=first_seen_at,
        )
        observations.append(observation)
        if pid in ignored_pids:
            continue
        if _is_baseline_descendant(observation):
            ignored_pids.add(pid)
            continue
        eligible_observations.append(observation)
    stale_pids = set(first_seen_by_pid) - set(descendants)
    for pid in stale_pids:
        first_seen_by_pid.pop(pid, None)
        ignored_pids.discard(pid)
    return detect_hung_process(
        eligible_observations,
        now=now,
        config=DetectorConfig(hung_timeout_seconds=timeout_seconds),
    )


def _live_descendant_pids(root_pid: int) -> tuple[int, ...]:
    try:
        root = psutil.Process(root_pid)
        return tuple(child.pid for child in root.children(recursive=True) if child.is_running())
    except PROCESS_LOOKUP_ERRORS:
        return ()


def _observe_descendant(
    *,
    root_pid: int,
    pid: int,
    observed_at: float,
    first_seen_at: float,
) -> ProcessObservation:
    try:
        process = psutil.Process(pid)
        parent_pid = process.ppid()
        command_line = tuple(process.cmdline())
        is_running = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        is_descendant = parent_pid == root_pid or any(
            parent.pid == root_pid for parent in process.parents()
        )
    except PROCESS_LOOKUP_ERRORS:
        parent_pid = None
        command_line = ()
        is_running = False
        is_descendant = False

    return ProcessObservation(
        evidence_id=f"agent_proc_{pid}_{int(observed_at * 1000)}",
        root_pid=root_pid,
        pid=pid,
        parent_pid=parent_pid,
        command_line=command_line,
        is_running=is_running,
        is_descendant=is_descendant,
        observed_at=observed_at,
        last_stdout_at=first_seen_at,
        last_stderr_at=first_seen_at,
    )


def _is_baseline_descendant(observation: ProcessObservation) -> bool:
    command = " ".join(observation.command_line)
    if _looks_like_user_command(command):
        return False
    return any(
        marker in command
        for marker in (
            "mcp/server.mjs",
            "node_repl",
            "codex-code-mode-host",
        )
    )


def _looks_like_user_command(command: str) -> bool:
    return any(
        marker in command
        for marker in (
            "python",
            "pytest",
            "node -e",
            "npm ",
            "bash",
            "zsh",
            "sh -c",
            "curl",
            "sleep",
        )
    )


def _persist_recent_observations(
    store: EvidenceStore,
    observations: list[ProcessObservation],
) -> None:
    if not observations:
        return
    by_pid: dict[int, ProcessObservation] = {}
    for observation in observations:
        by_pid[observation.pid] = observation
    store.add_process_observations(by_pid.values())


def _poll_exit_code(pid: int) -> int | None:
    try:
        finished_pid, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return 0
    if finished_pid == 0:
        return None
    return _status_code(status)


def _wait_exit_code(pid: int) -> int:
    try:
        _, status = os.waitpid(pid, 0)
    except ChildProcessError:
        return 0
    return _status_code(status)


def _status_code(status: int) -> int:
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 1


def _drain_master(master_fd: int, stdout_fd: int | None) -> None:
    while True:
        readable, _, _ = select.select([master_fd], (), (), 0)
        if not readable:
            return
        try:
            output = os.read(master_fd, 4096)
        except OSError:
            return
        if not output:
            return
        _write_output(stdout_fd, output)


def _terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size(fallback=(120, 40))
    columns = max(size.columns, 80)
    rows = max(size.lines, 24)
    return columns, rows


def _resize_child_pty(master_fd: int) -> None:
    columns, rows = _terminal_size()
    _set_window_size(master_fd, columns=columns, rows=rows)


def _set_window_size(fd: int, *, columns: int, rows: int) -> None:
    try:
        import fcntl
        import struct

        winsize = struct.pack("HHHH", rows, columns, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        return


def _write_status(message: str) -> None:
    os.write(sys.stderr.fileno(), message.encode("utf-8", errors="replace"))


def _write_output(stdout_fd: int | None, output: bytes) -> None:
    if stdout_fd is not None:
        os.write(stdout_fd, output)
        return
    sys.stdout.write(output.decode("utf-8", errors="replace"))
    sys.stdout.flush()


def _fileno_or_none(stream: object) -> int | None:
    fileno = getattr(stream, "fileno", None)
    if not callable(fileno):
        return None
    try:
        return int(fileno())
    except OSError:
        return None
