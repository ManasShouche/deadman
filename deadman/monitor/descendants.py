"""Shared descendant observation and hung-child detection.

Both the interactive PTY supervisor (`deadman agent`) and the attach
supervisor (`deadman attach`) monitor a process tree rooted at a Codex
process they do not own the stdout of. They share the same descendant
classification so recovery targeting stays identical and safe across modes.
"""

from __future__ import annotations

from pathlib import Path

import psutil

from deadman.detectors import detect_hung_process
from deadman.domain import DetectorConfig, ProcessObservation, Signal

PROCESS_LOOKUP_ERRORS = (
    psutil.NoSuchProcess,
    psutil.AccessDenied,
    psutil.ZombieProcess,
    PermissionError,
)


class DescendantTracker:
    """Track first-seen times and a persistent-process baseline for one root."""

    def __init__(self, root_pid: int, *, hung_timeout_seconds: float) -> None:
        self.root_pid = root_pid
        self.hung_timeout_seconds = hung_timeout_seconds
        self.first_seen_by_pid: dict[int, float] = {}
        self.ignored_pids: set[int] = set()
        self.observations: list[ProcessObservation] = []

    def poll(self, now: float) -> Signal | None:
        """Observe live descendants and return a hung signal if one is eligible."""

        descendants = live_descendant_pids(self.root_pid)
        eligible: list[ProcessObservation] = []
        for pid in descendants:
            first_seen_at = self.first_seen_by_pid.setdefault(pid, now)
            observation = observe_descendant(
                root_pid=self.root_pid,
                pid=pid,
                observed_at=now,
                first_seen_at=first_seen_at,
            )
            self.observations.append(observation)
            if pid in self.ignored_pids:
                continue
            if is_baseline_descendant(observation):
                self.ignored_pids.add(pid)
                continue
            eligible.append(observation)

        stale_pids = set(self.first_seen_by_pid) - set(descendants)
        for pid in stale_pids:
            self.first_seen_by_pid.pop(pid, None)
            self.ignored_pids.discard(pid)

        return detect_hung_process(
            eligible,
            now=now,
            config=DetectorConfig(hung_timeout_seconds=self.hung_timeout_seconds),
        )

    def watched_count(self) -> int:
        """Return how many non-baseline owned descendants are currently tracked."""

        return len(set(self.first_seen_by_pid) - self.ignored_pids)


def live_descendant_pids(root_pid: int) -> tuple[int, ...]:
    """Return the PIDs of running descendants of a root process."""

    try:
        root = psutil.Process(root_pid)
        return tuple(child.pid for child in root.children(recursive=True) if child.is_running())
    except PROCESS_LOOKUP_ERRORS:
        return ()


def observe_descendant(
    *,
    root_pid: int,
    pid: int,
    observed_at: float,
    first_seen_at: float,
) -> ProcessObservation:
    """Capture one descendant observation relative to a root process."""

    try:
        process = psutil.Process(pid)
        parent_pid = process.ppid()
        command_line = tuple(process.cmdline())
        is_running = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        is_descendant = parent_pid == root_pid or any(
            parent.pid == root_pid for parent in process.parents()
        )
        # A process listening on a port is a persistent service (dev server, DB),
        # not a hung command. The hung detector exempts it, so it must be observed.
        listening_ports = _listening_ports(process) if is_running else ()
    except PROCESS_LOOKUP_ERRORS:
        parent_pid = None
        command_line = ()
        is_running = False
        is_descendant = False
        listening_ports = ()

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
        listening_ports=listening_ports,
    )


def _listening_ports(process: psutil.Process) -> tuple[int, ...]:
    """Return the ports a process is listening on, empty if none or inaccessible."""

    try:
        connections = process.net_connections(kind="inet")
    except PROCESS_LOOKUP_ERRORS:
        return ()
    ports = [
        int(connection.laddr.port)
        for connection in connections
        if connection.status == psutil.CONN_LISTEN and connection.laddr
    ]
    return tuple(sorted(ports))


# Persistent Codex helper executables observed in a live Codex 0.144.4 tree.
# The interactive Codex CLI is `node <path>/codex` -> `codex` (rust binary),
# which spawns `node_repl`, `node ./mcp/server.mjs`, and `codex-code-mode-host`.
# None of these are recoverable user work, so they are never termination targets.
BASELINE_HELPER_EXECUTABLES = frozenset(
    {"codex", "node_repl", "codex-code-mode-host"}
)


def is_baseline_descendant(observation: ProcessObservation) -> bool:
    """Classify a persistent, non-recoverable Codex helper process from its argv."""

    command_line = observation.command_line
    executable = executable_name(command_line)
    # The interactive Codex process carries the user's prompt in argv. Never
    # classify it from arbitrary prompt text such as "run Python".
    if executable in BASELINE_HELPER_EXECUTABLES:
        return True
    if _runs_codex_mcp_server(command_line):
        return True
    return False


def _runs_codex_mcp_server(command_line: tuple[str, ...]) -> bool:
    """Match Codex's MCP server regardless of how its path is spelled in argv.

    Observed as `node ./mcp/server.mjs`; a bare element check misses the
    `./` prefix, so match any argument path that ends in `mcp/server.mjs`.
    """

    return any(token.replace("\\", "/").endswith("mcp/server.mjs") for token in command_line)


def executable_name(command_line: tuple[str, ...]) -> str:
    """Return the lowercase basename of the executable in argv."""

    if not command_line:
        return ""
    return Path(command_line[0]).name.lower()
