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


def is_baseline_descendant(observation: ProcessObservation) -> bool:
    """Classify a persistent, non-recoverable helper process from its argv."""

    command_line = observation.command_line
    executable = executable_name(command_line)
    # The interactive Codex process carries the user's prompt in argv. Never
    # classify it from arbitrary prompt text such as "run Python".
    if executable == "codex":
        return True
    if looks_like_user_command(command_line):
        return False
    return executable in {"node_repl", "codex-code-mode-host"} or "mcp/server.mjs" in command_line


def looks_like_user_command(command_line: tuple[str, ...]) -> bool:
    """Return whether argv looks like a recoverable user-launched command."""

    executable = executable_name(command_line)
    if executable in {"pytest", "npm", "bash", "zsh", "sh", "curl", "sleep"}:
        return True
    if "python" in executable:
        return True
    return executable == "node" and "-e" in command_line[1:]


def executable_name(command_line: tuple[str, ...]) -> str:
    """Return the lowercase basename of the executable in argv."""

    if not command_line:
        return ""
    return Path(command_line[0]).name.lower()
