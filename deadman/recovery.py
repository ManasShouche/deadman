"""Shared hung-descendant recovery for owned-root supervisors.

`deadman agent` (interactive PTY) and `deadman attach` (external Codex
process) both supervise a process tree rooted at a Codex PID they can prove
ownership of through the OS process table. When a hung descendant is
detected they run the identical bounded recovery here: diagnose, authorize,
terminate the proven descendant, verify it is gone, and record an auditable
incident.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import psutil

from deadman.domain import (
    ActionResult,
    Diagnosis,
    Incident,
    PolicyDecision,
    RecoveryAction,
    Signal,
    VerificationResult,
)
from deadman.executor import terminate_descendant_process
from deadman.incidents import record_recovery_incident
from deadman.monitor import ProcessMonitor
from deadman.policy import PolicyEngine
from deadman.store import EvidenceStore

PROCESS_LOOKUP_ERRORS = (
    psutil.NoSuchProcess,
    psutil.AccessDenied,
    psutil.ZombieProcess,
    PermissionError,
)


class DiagnosisClient(Protocol):
    """Client boundary for evidence-bound diagnosis."""

    def diagnose(self, signal: Signal) -> Diagnosis:
        """Return a typed recovery recommendation for one signal."""


@dataclass(frozen=True)
class RecoveryOutcome:
    """Result of one hung-descendant recovery attempt."""

    status: str
    signal: Signal
    diagnosis: Diagnosis
    policy: PolicyDecision
    action_result: ActionResult | None
    verification: VerificationResult | None
    incident: Incident | None

    @property
    def message(self) -> str:
        if self.action_result is not None:
            return self.action_result.message
        if self.verification is not None:
            return self.verification.reason
        return self.policy.reason


def recover_hung_descendant(
    store: EvidenceStore,
    *,
    session_id: str,
    root_pid: int,
    signal: Signal,
    diagnosis_client: DiagnosisClient,
    auto_recover: bool,
    mode: str,
) -> RecoveryOutcome:
    """Diagnose, authorize, terminate, verify, and record one hung descendant."""

    diagnosis = diagnosis_client.diagnose(signal)
    policy = PolicyEngine(auto_recover=auto_recover).evaluate(
        diagnosis,
        signal,
        action_fingerprint=f"action:{signal.fingerprint}",
        known_evidence_ids=signal.evidence_ids,
    )

    action_result: ActionResult | None = None
    verification: VerificationResult | None = None

    if not policy.allowed:
        # No action executed; the incident rests in AWAITING_APPROVAL.
        status = "awaiting_approval"
    elif policy.action is RecoveryAction.TERMINATE_DESCENDANT_PROCESS:
        target_pid = int(signal.details["pid"])
        action_result = terminate_descendant_process(
            root_pid=root_pid,
            target_pid=target_pid,
            evidence_id=signal.evidence_ids[0],
        )
        verification = _verify_descendant_gone(root_pid, target_pid, action_result)
        status = "recovered" if verification.resolved else "escalated"
    else:
        # An allowed but unexecutable action escalates via action_result=None.
        status = "escalated"

    report = _recovery_report(
        mode=mode,
        status=status,
        signal=signal,
        diagnosis=diagnosis,
        policy=policy,
        action_result=action_result,
        verification=verification,
    )
    incident = record_recovery_incident(
        store,
        session_id=session_id,
        signal=signal,
        diagnosis=diagnosis,
        policy=policy,
        action_result=action_result,
        verification=verification,
        report=report,
    )
    return RecoveryOutcome(
        status=status,
        signal=signal,
        diagnosis=diagnosis,
        policy=policy,
        action_result=action_result,
        verification=verification,
        incident=incident,
    )


def _verify_descendant_gone(
    root_pid: int,
    target_pid: int,
    action_result: ActionResult,
) -> VerificationResult:
    if not action_result.succeeded:
        return VerificationResult(
            resolved=False,
            changed_progress_fingerprint=False,
            success_signal=None,
            reason=action_result.message,
        )

    if _still_live_descendant(root_pid, target_pid):
        return VerificationResult(
            resolved=False,
            changed_progress_fingerprint=False,
            success_signal=None,
            reason="hung descendant remained after termination",
        )
    return VerificationResult(
        resolved=True,
        changed_progress_fingerprint=True,
        success_signal="hung descendant terminated; supervised session freed",
        reason="hung descendant no longer present; interactive session can proceed",
    )


def _still_live_descendant(root_pid: int, target_pid: int) -> bool:
    """Return whether the target is still a live, non-zombie descendant of root.

    A terminated child often lingers as a zombie until its real parent (Codex)
    reaps it. A zombie is effectively gone, so it is not treated as a remaining
    hung descendant.
    """

    if not ProcessMonitor(root_pid).is_descendant(target_pid):
        return False
    try:
        process = psutil.Process(target_pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except PROCESS_LOOKUP_ERRORS:
        return False


def _recovery_report(
    *,
    mode: str,
    status: str,
    signal: Signal,
    diagnosis: Diagnosis,
    policy: PolicyDecision,
    action_result: ActionResult | None,
    verification: VerificationResult | None,
) -> str:
    lines = [
        f"Mode: {mode}",
        f"Status: {status}",
        f"Signal: {signal.kind.value}",
        f"Hung pid: {signal.details.get('pid')}",
        f"Root pid: {signal.details.get('root_pid')}",
        f"Recommended action: {diagnosis.recommended_action.value}",
        f"Policy: {'allowed' if policy.allowed else policy.reason}",
    ]
    if action_result is not None:
        lines.append(f"Action: {action_result.message}")
    if verification is not None:
        lines.append(f"Verification: {'resolved' if verification.resolved else 'escalated'}")
        lines.append(f"Verification reason: {verification.reason}")
    lines.append(f"Guidance: {diagnosis.guidance}")
    return "\n".join(lines)
