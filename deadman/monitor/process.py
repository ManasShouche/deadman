"""Process ownership and liveness observations."""

from __future__ import annotations

import time

import psutil

from deadman.domain import ProcessObservation

PROTECTED_PIDS = frozenset({0, 1})
PROCESS_LOOKUP_ERRORS = (
    psutil.NoSuchProcess,
    psutil.AccessDenied,
    psutil.ZombieProcess,
    PermissionError,
)


class ProcessMonitor:
    """Observe processes relative to a supervised root PID."""

    def __init__(self, root_pid: int) -> None:
        if root_pid in PROTECTED_PIDS:
            raise ValueError(f"refusing protected root pid: {root_pid}")
        self.root_pid = root_pid

    def is_descendant(self, pid: int) -> bool:
        """Return whether pid currently descends from the supervised root."""

        if pid in PROTECTED_PIDS or pid == self.root_pid:
            return False

        try:
            process = psutil.Process(pid)
            parents = process.parents()
        except PROCESS_LOOKUP_ERRORS:
            return False

        return any(parent.pid == self.root_pid for parent in parents)

    def observe(
        self,
        pid: int,
        *,
        evidence_id: str | None = None,
        observed_at: float | None = None,
        last_stdout_at: float | None = None,
        last_stderr_at: float | None = None,
        ready_pattern_matched: bool = False,
    ) -> ProcessObservation:
        """Capture one process observation without signalling or mutating it."""

        observed = time.monotonic() if observed_at is None else observed_at
        generated_id = evidence_id or f"proc_{pid}_{int(observed * 1000)}"

        try:
            process = psutil.Process(pid)
            parent_pid = process.ppid()
            command_line = tuple(process.cmdline())
            is_running = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
            listening_ports = _listening_ports(process)
        except PROCESS_LOOKUP_ERRORS:
            parent_pid = None
            command_line = ()
            is_running = False
            listening_ports = ()

        return ProcessObservation(
            evidence_id=generated_id,
            root_pid=self.root_pid,
            pid=pid,
            parent_pid=parent_pid,
            command_line=command_line,
            is_running=is_running,
            is_descendant=self.is_descendant(pid),
            observed_at=observed,
            last_stdout_at=last_stdout_at,
            last_stderr_at=last_stderr_at,
            listening_ports=listening_ports,
            ready_pattern_matched=ready_pattern_matched,
        )


def _listening_ports(process: psutil.Process) -> tuple[int, ...]:
    ports: list[int] = []
    try:
        connections = process.net_connections(kind="inet")
    except PROCESS_LOOKUP_ERRORS:
        return ()

    for connection in connections:
        if connection.status == psutil.CONN_LISTEN and connection.laddr:
            ports.append(int(connection.laddr.port))
    return tuple(sorted(ports))
