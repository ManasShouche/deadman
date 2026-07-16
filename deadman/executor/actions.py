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

    try:
        process.terminate()
        process.wait(timeout=terminate_timeout_seconds)
        return _result(True, True, evidence_id, "terminated descendant process")
    except psutil.TimeoutExpired:
        if not monitor.is_descendant(target_pid):
            return _result(True, False, evidence_id, "target ancestry changed before kill")
        process.kill()
        process.wait(timeout=terminate_timeout_seconds)
        return _result(True, True, evidence_id, "killed descendant process after timeout")
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


def _safe_name(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "-_" else "-" for character in value
    )
    return cleaned.strip("-") or f"incident-{int(time.time())}"
