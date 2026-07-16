"""Live supervision pipeline."""

from __future__ import annotations

import select
import subprocess
import time
from pathlib import Path
from typing import Protocol

import psutil

from deadman.adapter import CapturedRun, parse_jsonl_lines, run_and_capture_jsonl
from deadman.detectors import detect_hung_process
from deadman.diagnosis import FakeDiagnosisClient
from deadman.domain import (
    ActionResult,
    DetectorConfig,
    Diagnosis,
    PolicyDecision,
    ProcessObservation,
    RecoveryAction,
    RunSummary,
    Signal,
    VerificationResult,
)
from deadman.executor import terminate_descendant_process
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


def run_supervised_command(
    argv: tuple[str, ...],
    *,
    workspace: Path,
    database_path: Path | None = None,
    timeout_seconds: float | None = None,
    auto_recover: bool = False,
    hung_timeout_seconds: float | None = None,
    diagnosis_client: DiagnosisClient | None = None,
) -> RunSummary:
    """Run a command, persist adapter evidence, and summarize deterministic status."""

    db_path = database_path or workspace / ".deadman" / "deadman.sqlite"
    if hung_timeout_seconds is not None:
        return _run_live_supervised_command(
            argv,
            database_path=db_path,
            timeout_seconds=timeout_seconds,
            auto_recover=auto_recover,
            hung_timeout_seconds=hung_timeout_seconds,
            diagnosis_client=diagnosis_client or FakeDiagnosisClient(),
        )

    captured = run_and_capture_jsonl(argv, timeout_seconds=timeout_seconds)
    store = EvidenceStore(db_path)
    store.add_raw_events(captured.parsed.raw_events)
    store.add_normalized_events(captured.parsed.normalized_events)
    store.add_capability_report(captured.parsed.capabilities)

    status = _status(captured.returncode, captured.parsed.capabilities.has_completion_events)
    report = _report(captured, status)
    return RunSummary(
        argv=captured.argv,
        returncode=captured.returncode,
        database_path=str(db_path),
        raw_event_count=len(captured.parsed.raw_events),
        normalized_event_count=len(captured.parsed.normalized_events),
        session_id=captured.parsed.capabilities.persisted_session_id,
        status=status,
        report=report,
    )


def _run_live_supervised_command(
    argv: tuple[str, ...],
    *,
    database_path: Path,
    timeout_seconds: float | None,
    auto_recover: bool,
    hung_timeout_seconds: float,
    diagnosis_client: DiagnosisClient,
) -> RunSummary:
    """Stream a supervised process long enough to detect and recover a hung child."""

    if not argv:
        raise ValueError("argv must not be empty")

    started_at = time.monotonic()
    last_stdout_at: float | None = started_at
    last_stderr_at: float | None = started_at
    stdout_lines: list[str] = []
    observations: list[ProcessObservation] = []
    signal: Signal | None = None
    diagnosis: Diagnosis | None = None
    policy: PolicyDecision | None = None
    action_result: ActionResult | None = None
    verification: VerificationResult | None = None
    status = "running"

    process = subprocess.Popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        bufsize=1,
    )
    deadline = None if timeout_seconds is None else started_at + timeout_seconds

    try:
        while process.poll() is None:
            now = time.monotonic()
            last_times: dict[str, float] = {}
            _drain_available_output(process, stdout_lines, now, last_times)
            last_stdout_at = last_times.get("stdout", last_stdout_at)
            last_stderr_at = last_times.get("stderr", last_stderr_at)

            if deadline is not None and now >= deadline:
                status = "timed_out"
                break

            descendants = _live_descendant_pids(process.pid)
            for pid in descendants:
                observation = _observe_descendant(
                    root_pid=process.pid,
                    pid=pid,
                    observed_at=now,
                    last_stdout_at=last_stdout_at,
                    last_stderr_at=last_stderr_at,
                )
                observations.append(observation)

            signal = detect_hung_process(
                observations[-len(descendants) :] if descendants else (),
                now=now,
                config=_hung_config(hung_timeout_seconds),
            )
            if signal is None:
                time.sleep(0.05)
                continue

            diagnosis = diagnosis_client.diagnose(signal)
            policy = PolicyEngine(auto_recover=auto_recover).evaluate(
                diagnosis,
                signal,
                action_fingerprint=f"action:{signal.fingerprint}",
                known_evidence_ids=signal.evidence_ids,
            )
            if not policy.allowed:
                status = "awaiting_approval"
                verification = VerificationResult(
                    resolved=False,
                    changed_progress_fingerprint=False,
                    success_signal=None,
                    reason=f"policy blocked: {policy.reason}",
                )
                break

            if policy.action is RecoveryAction.TERMINATE_DESCENDANT_PROCESS:
                target_pid = int(signal.details["pid"])
                action_result = terminate_descendant_process(
                    root_pid=process.pid,
                    target_pid=target_pid,
                    evidence_id=signal.evidence_ids[0],
                )
                verification = _verify_live_termination(process, action_result)
                status = "recovered" if verification.resolved else "escalated"
                break

            status = "escalated"
            verification = VerificationResult(
                resolved=False,
                changed_progress_fingerprint=False,
                success_signal=None,
                reason=f"live run does not execute {policy.action.value}",
            )
            break
    finally:
        if status in {"awaiting_approval", "escalated", "timed_out"}:
            _terminate_process_tree(process.pid)
        if status in {"awaiting_approval", "escalated", "timed_out"} and process.poll() is None:
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        _drain_remaining_output(process, stdout_lines)

    returncode = process.poll()
    if returncode is None:
        returncode = process.wait(timeout=1.0)

    parsed = parse_jsonl_lines(tuple(stdout_lines))
    store = EvidenceStore(database_path)
    store.add_raw_events(parsed.raw_events)
    store.add_normalized_events(parsed.normalized_events)
    store.add_capability_report(parsed.capabilities)
    store.add_process_observations(observations)
    if signal is not None:
        store.add_signals((signal,))

    if status == "running":
        status = _status(returncode, parsed.capabilities.has_completion_events)

    report = _live_report(
        returncode=returncode,
        raw_event_count=len(parsed.raw_events),
        normalized_event_count=len(parsed.normalized_events),
        session_id=parsed.capabilities.persisted_session_id,
        status=status,
        signal=signal,
        diagnosis=diagnosis,
        policy=policy,
        action_result=action_result,
        verification=verification,
    )
    return RunSummary(
        argv=argv,
        returncode=returncode,
        database_path=str(database_path),
        raw_event_count=len(parsed.raw_events),
        normalized_event_count=len(parsed.normalized_events),
        session_id=parsed.capabilities.persisted_session_id,
        status=status,
        report=report,
        incident_id=_incident_id(signal),
        signal_kind=signal.kind if signal is not None else None,
        recommended_action=diagnosis.recommended_action if diagnosis is not None else None,
        policy_allowed=policy.allowed if policy is not None else None,
        verification_resolved=verification.resolved if verification is not None else None,
    )


def _status(returncode: int, has_completion_events: bool) -> str:
    if returncode == 0 and has_completion_events:
        return "completed"
    if returncode == 0:
        return "completed_without_adapter_completion"
    return "exited_nonzero"


def _report(captured: CapturedRun, status: str) -> str:
    return "\n".join(
        [
            f"Status: {status}",
            f"Return code: {captured.returncode}",
            f"Raw events: {len(captured.parsed.raw_events)}",
            f"Normalized events: {len(captured.parsed.normalized_events)}",
            f"Session ID: {captured.parsed.capabilities.persisted_session_id or 'unknown'}",
        ]
    )


def _drain_available_output(
    process: subprocess.Popen[str],
    stdout_lines: list[str],
    now: float,
    last_times: dict[str, float],
) -> None:
    streams = [stream for stream in (process.stdout, process.stderr) if stream is not None]
    if not streams:
        return

    readable, _, _ = select.select(streams, (), (), 0)
    for stream in readable:
        line = stream.readline()
        if not line:
            continue
        if stream is process.stdout:
            stdout_lines.append(line.rstrip("\n"))
            last_times["stdout"] = now
        else:
            last_times["stderr"] = now


def _drain_remaining_output(process: subprocess.Popen[str], stdout_lines: list[str]) -> None:
    streams = [stream for stream in (process.stdout, process.stderr) if stream is not None]
    while streams:
        readable, _, _ = select.select(streams, (), (), 0)
        if not readable:
            return
        for stream in readable:
            line = stream.readline()
            if not line:
                streams.remove(stream)
                continue
            if stream is process.stdout:
                stdout_lines.append(line.rstrip("\n"))


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
    last_stdout_at: float | None,
    last_stderr_at: float | None,
) -> ProcessObservation:
    try:
        process = psutil.Process(pid)
        parent_pid = process.ppid()
        command_line = tuple(process.cmdline())
        is_running = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        is_descendant = any(parent.pid == root_pid for parent in process.parents())
    except PROCESS_LOOKUP_ERRORS:
        parent_pid = None
        command_line = ()
        is_running = False
        is_descendant = False

    return ProcessObservation(
        evidence_id=f"proc_{pid}_{int(observed_at * 1000)}",
        root_pid=root_pid,
        pid=pid,
        parent_pid=parent_pid,
        command_line=command_line,
        is_running=is_running,
        is_descendant=is_descendant,
        observed_at=observed_at,
        last_stdout_at=last_stdout_at,
        last_stderr_at=last_stderr_at,
    )


def _hung_config(timeout_seconds: float) -> DetectorConfig:
    return DetectorConfig(hung_timeout_seconds=timeout_seconds)


def _terminate_process_tree(root_pid: int) -> None:
    try:
        root = psutil.Process(root_pid)
        descendants = root.children(recursive=True)
    except PROCESS_LOOKUP_ERRORS:
        descendants = []

    for child in descendants:
        try:
            child.terminate()
        except PROCESS_LOOKUP_ERRORS:
            pass

    gone, alive = psutil.wait_procs(descendants, timeout=0.5)
    _ = gone
    for child in alive:
        try:
            child.kill()
        except PROCESS_LOOKUP_ERRORS:
            pass

    try:
        psutil.Process(root_pid).terminate()
    except PROCESS_LOOKUP_ERRORS:
        pass


def _verify_live_termination(
    process: subprocess.Popen[str],
    action_result: ActionResult,
) -> VerificationResult:
    if not action_result.succeeded:
        return VerificationResult(
            resolved=False,
            changed_progress_fingerprint=False,
            success_signal=None,
            reason=action_result.message,
        )

    try:
        returncode = process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        return VerificationResult(
            resolved=False,
            changed_progress_fingerprint=False,
            success_signal=None,
            reason="parent run did not react within verification window",
        )

    return VerificationResult(
        resolved=returncode == 0,
        changed_progress_fingerprint=True,
        success_signal="supervised process exited after descendant termination"
        if returncode == 0
        else None,
        reason="verified parent completion after descendant termination"
        if returncode == 0
        else f"parent exited nonzero after recovery: {returncode}",
    )


def _live_report(
    *,
    returncode: int,
    raw_event_count: int,
    normalized_event_count: int,
    session_id: str | None,
    status: str,
    signal: Signal | None,
    diagnosis: Diagnosis | None,
    policy: PolicyDecision | None,
    action_result: ActionResult | None,
    verification: VerificationResult | None,
) -> str:
    lines = [
        f"Status: {status}",
        f"Return code: {returncode}",
        f"Raw events: {raw_event_count}",
        f"Normalized events: {normalized_event_count}",
        f"Session ID: {session_id or 'unknown'}",
    ]
    if signal is not None:
        lines.append(f"Signal: {signal.kind.value}")
    if diagnosis is not None:
        lines.append(f"Recommended action: {diagnosis.recommended_action.value}")
    if policy is not None:
        lines.append(f"Policy: {'allowed' if policy.allowed else policy.reason}")
    if action_result is not None:
        lines.append(f"Action: {action_result.message}")
    if verification is not None:
        lines.append(f"Verification: {'resolved' if verification.resolved else 'escalated'}")
        lines.append(f"Verification reason: {verification.reason}")
    return "\n".join(lines)


def _incident_id(signal: Signal | None) -> str | None:
    if signal is None:
        return None
    suffix = signal.fingerprint.split(":", maxsplit=1)[-1]
    return f"live-{signal.kind.value.lower()}-{suffix}"
