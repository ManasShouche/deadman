"""Bounded deterministic recovery action executors."""

from __future__ import annotations

import os
import time
from pathlib import Path

import psutil

from deadman.domain import ActionResult, RecoveryAction
from deadman.monitor import PROTECTED_PIDS, ProcessMonitor

PROCESS_LOOKUP_ERRORS = (
    psutil.NoSuchProcess,
    psutil.AccessDenied,
    psutil.ZombieProcess,
    PermissionError,
)


def terminate_descendant_process(
    *,
    root_pid: int,
    target_pid: int,
    evidence_id: str,
    terminate_timeout_seconds: float = 2.0,
) -> ActionResult:
    """Terminate only a freshly proven descendant of the supervised root."""

    protected = PROTECTED_PIDS | {os.getpid(), os.getppid(), root_pid}
    if target_pid in protected:
        return _result(False, False, evidence_id, f"refusing protected pid {target_pid}")

    monitor = ProcessMonitor(root_pid)
    if not monitor.is_descendant(target_pid):
        return _result(False, False, evidence_id, "target pid is not a proven descendant")

    try:
        process = psutil.Process(target_pid)
    except PROCESS_LOOKUP_ERRORS:
        return _result(False, False, evidence_id, "target process is not live")

    if not monitor.is_descendant(target_pid):
        return _result(False, False, evidence_id, "target ancestry changed before signalling")

    targets = _owned_target_subtree(process, monitor)
    if not targets:
        return _result(False, False, evidence_id, "target subtree is not a proven descendant")

    try:
        _terminate_processes(targets)
        _, alive = psutil.wait_procs(targets, timeout=terminate_timeout_seconds)
        if alive:
            if not monitor.is_descendant(target_pid):
                return _result(True, False, evidence_id, "target ancestry changed before kill")
            _kill_processes(alive)
            _, alive = psutil.wait_procs(alive, timeout=terminate_timeout_seconds)
        if alive:
            return _result(True, False, evidence_id, "target subtree did not exit after kill")
        if len(targets) == 1:
            return _result(True, True, evidence_id, "terminated descendant process")
        return _result(
            True,
            True,
            evidence_id,
            f"terminated descendant process tree ({len(targets)} processes)",
        )
    except PROCESS_LOOKUP_ERRORS as exc:
        return _result(True, False, evidence_id, f"termination failed: {exc}")


def write_checkpoint_handoff(
    *,
    workspace: Path,
    incident_id: str,
    guidance: str,
    original_task: str,
) -> ActionResult:
    """Write an untracked checkpoint handoff under .deadman/handoffs."""

    handoff_dir = workspace / ".deadman" / "handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = handoff_dir / f"{_safe_name(incident_id)}.md"
    handoff_path.write_text(
        "\n".join(
            [
                "# Deadman checkpoint handoff",
                "",
                f"Incident: {incident_id}",
                "",
                "## Original task",
                "",
                original_task,
                "",
                "## Guidance",
                "",
                guidance,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return ActionResult(
        action=RecoveryAction.CHECKPOINT_AND_RESPAWN,
        attempted=True,
        succeeded=True,
        message="wrote checkpoint handoff",
        artifact_path=str(handoff_path),
    )


def _result(attempted: bool, succeeded: bool, evidence_id: str, message: str) -> ActionResult:
    return ActionResult(
        action=RecoveryAction.TERMINATE_DESCENDANT_PROCESS,
        attempted=attempted,
        succeeded=succeeded,
        evidence_ids=(evidence_id,),
        message=message,
    )


def _owned_target_subtree(
    process: psutil.Process,
    monitor: ProcessMonitor,
) -> list[psutil.Process]:
    try:
        descendants = process.children(recursive=True)
    except PROCESS_LOOKUP_ERRORS:
        descendants = []

    targets = [child for child in descendants if monitor.is_descendant(child.pid)]
    if monitor.is_descendant(process.pid):
        targets.append(process)
    # Signal leaves before their parent so subprocess waiters wake naturally.
    return list(reversed(targets))


def _terminate_processes(processes: list[psutil.Process]) -> None:
    for process in processes:
        try:
            process.terminate()
        except PROCESS_LOOKUP_ERRORS:
            pass


def _kill_processes(processes: list[psutil.Process]) -> None:
    for process in processes:
        try:
            process.kill()
        except PROCESS_LOOKUP_ERRORS:
            pass


def _safe_name(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "-_" else "-" for character in value
    )
    return cleaned.strip("-") or f"incident-{int(time.time())}"
