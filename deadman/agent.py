"""PTY wrapper for supervising the interactive Codex CLI."""

from __future__ import annotations

import os
import select
import shutil
import signal as signal_module
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    import pty as _pty
    import termios as _termios
    import tty as _tty
except ModuleNotFoundError:
    pty: Any | None = None
    termios: Any | None = None
    tty: Any | None = None
else:
    pty = _pty
    termios = _termios
    tty = _tty

from deadman.diagnosis import FakeDiagnosisClient
from deadman.domain import (
    ProcessObservation,
    SessionMode,
    SessionOwnership,
    SessionRecord,
)
from deadman.monitor import DescendantTracker
from deadman.paths import default_database_path, project_root
from deadman.platforms import supports_pty_supervision
from deadman.recovery import DiagnosisClient, recover_hung_descendant
from deadman.store import EvidenceStore

STATUS_INTERVAL_SECONDS = 10.0


def run_agent_cli(
    argv: Sequence[str],
    *,
    workspace: Path,
    database_path: Path | None = None,
    hung_timeout_seconds: float = 60.0,
    auto_recover: bool = False,
    diagnosis_client: DiagnosisClient | None = None,
) -> int:
    """Run an interactive CLI in a PTY while supervising its process tree."""

    if not argv:
        raise ValueError("argv must not be empty")
    if not supports_pty_supervision() or pty is None or termios is None or tty is None:
        raise RuntimeError(
            "deadman agent requires a POSIX PTY; on Windows, start Codex normally "
            "and use deadman attach from the same repository"
        )

    root = project_root(workspace)
    db_path = database_path or default_database_path(root)
    store = EvidenceStore(db_path)
    diagnostician = diagnosis_client or FakeDiagnosisClient()
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
    sigwinch = _required_int_capability(signal_module, "SIGWINCH")
    old_sigwinch = signal_module.getsignal(sigwinch)
    signal_module.signal(
        sigwinch,
        lambda _signum, _frame: _resize_child_pty(master_fd),
    )
    if stdin_fd is not None and sys.stdin.isatty():
        old_tty = termios.tcgetattr(stdin_fd)
        tty.setraw(stdin_fd)

    session_started_at = time.time()
    session_id = f"agent:{child_pid}"
    store.upsert_session(
        SessionRecord(
            session_id=session_id,
            mode=SessionMode.MANAGED,
            source="agent_pty",
            cwd=str(root),
            ownership=SessionOwnership.MANAGED,
            status="supervising",
            started_at=session_started_at,
            last_seen_at=session_started_at,
        )
    )

    last_status_at = 0.0
    tracker = DescendantTracker(child_pid, hung_timeout_seconds=hung_timeout_seconds)
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

            if stdin_fd is not None and stdin_fd in readable:
                user_input = os.read(stdin_fd, 4096)
                if user_input:
                    os.write(master_fd, user_input)

            signal = tracker.poll(now)
            if now - last_status_at >= STATUS_INTERVAL_SECONDS:
                _persist_recent_observations(store, tracker.observations, session_id)
                _write_status(
                    f"\n[deadman] monitoring {tracker.watched_count()} owned descendant(s); "
                    f"ignored baseline={len(tracker.ignored_pids)}\n"
                )
                last_status_at = now
            if signal is None or signal.fingerprint in recovered_fingerprints:
                continue

            _persist_recent_observations(store, tracker.observations, session_id)
            store.add_signals((signal,), session_id=session_id)
            recovered_fingerprints.add(signal.fingerprint)
            _write_status(
                f"\n[deadman] HUNG_PROCESS detected for pid {signal.details['pid']}\n"
            )
            outcome = recover_hung_descendant(
                store,
                session_id=session_id,
                root_pid=child_pid,
                signal=signal,
                diagnosis_client=diagnostician,
                auto_recover=auto_recover,
                mode="agent",
            )
            _write_status(f"[deadman] {outcome.status}: {outcome.message}\n")
    finally:
        signal_module.signal(sigwinch, old_sigwinch)
        if old_tty is not None and stdin_fd is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_tty)
        try:
            os.close(master_fd)
        except OSError:
            pass


def _persist_recent_observations(
    store: EvidenceStore,
    observations: list[ProcessObservation],
    session_id: str,
) -> None:
    if not observations:
        return
    by_pid: dict[int, ProcessObservation] = {}
    for observation in observations:
        by_pid[observation.pid] = observation
    store.add_process_observations(by_pid.values(), session_id=session_id)


def _poll_exit_code(pid: int) -> int | None:
    try:
        finished_pid, status = os.waitpid(pid, _required_int_capability(os, "WNOHANG"))
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
    signal_number = status & 0x7F
    if signal_number == 0:
        return (status >> 8) & 0xFF
    if signal_number != 0x7F:
        return 128 + signal_number
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
    if termios is None:
        return
    try:
        import fcntl
        import struct

        winsize = struct.pack("HHHH", rows, columns, 0, 0)
        ioctl = getattr(fcntl, "ioctl", None)
        if callable(ioctl):
            ioctl(fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        return


def _required_int_capability(module: object, name: str) -> int:
    value = getattr(module, name, None)
    if not isinstance(value, int):
        raise RuntimeError(f"required POSIX capability is unavailable: {name}")
    return value


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
