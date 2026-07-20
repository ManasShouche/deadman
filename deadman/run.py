"""Live supervision pipeline."""

from __future__ import annotations

import select
import subprocess
import time
from pathlib import Path
from typing import Protocol

import psutil

from deadman.adapter import (
    AdapterParseResult,
    CapturedRun,
    parse_jsonl_lines,
    persist_managed_events,
    run_and_capture_jsonl,
)
from deadman.detectors import detect_hung_process
from deadman.diagnosis import FakeDiagnosisClient
from deadman.domain import (
    ActionResult,
    DetectorConfig,
    Diagnosis,
    Incident,
    IncidentState,
    NormalizedEvent,
    PolicyDecision,
    ProcessObservation,
    RecoveryAction,
    RunSummary,
    Signal,
    VerificationResult,
)
from deadman.domain.incident import transition_incident
from deadman.executor import terminate_descendant_process
from deadman.paths import default_database_path, project_root
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
    diagnosis_backend: str | None = None,
    resume_after_recovery: bool = False,
    resume_argv: tuple[str, ...] | None = None,
) -> RunSummary:
    """Run a command, persist adapter evidence, and summarize deterministic status."""

    root = project_root(workspace)
    db_path = database_path or default_database_path(root)
    if hung_timeout_seconds is not None:
        return _run_live_supervised_command(
            argv,
            workspace=root,
            database_path=db_path,
            timeout_seconds=timeout_seconds,
            auto_recover=auto_recover,
            hung_timeout_seconds=hung_timeout_seconds,
            diagnosis_client=diagnosis_client or FakeDiagnosisClient(),
            diagnosis_backend=diagnosis_backend,
            resume_after_recovery=resume_after_recovery,
            resume_argv=resume_argv,
        )

    captured = run_and_capture_jsonl(argv, timeout_seconds=timeout_seconds)
    store = EvidenceStore(db_path)
    store.add_raw_events(captured.parsed.raw_events)
    store.add_normalized_events(captured.parsed.normalized_events)
    store.add_capability_report(captured.parsed.capabilities)
    persist_managed_events(captured.parsed, workspace=root, store=store)

    status = _status(captured.returncode, captured.parsed.capabilities.has_completion_events)
    lingering = _find_lingering_command(captured.parsed.normalized_events)
    resume_result = _maybe_resume_lingering_command(
        original_argv=argv,
        parsed=captured.parsed,
        lingering=lingering,
        enabled=auto_recover,
        resume_argv=resume_argv,
        timeout_seconds=timeout_seconds,
    )
    if lingering is not None and resume_result is None:
        status = "awaiting_approval"
    if resume_result is not None:
        status = "recovered_and_resumed" if _resume_succeeded(resume_result) else "escalated"
        persist_managed_events(resume_result.parsed, workspace=root, store=store)
    report = _report(captured, status, resume_result=resume_result)
    return RunSummary(
        argv=captured.argv,
        returncode=captured.returncode,
        database_path=str(db_path),
        raw_event_count=len(captured.parsed.raw_events),
        normalized_event_count=len(captured.parsed.normalized_events),
        session_id=captured.parsed.capabilities.persisted_session_id,
        status=status,
        report=report,
        policy_allowed=_lingering_policy_allowed(lingering, resume_result),
        verification_resolved=_lingering_verification_resolved(lingering, resume_result),
        diagnosis_backend=diagnosis_backend,
        resume_attempted=resume_result is not None,
        resume_returncode=resume_result.returncode if resume_result is not None else None,
        resume_status=_resume_status(resume_result) if resume_result is not None else None,
        resume_raw_event_count=_resume_raw_event_count(resume_result),
    )


def _run_live_supervised_command(
    argv: tuple[str, ...],
    *,
    workspace: Path,
    database_path: Path,
    timeout_seconds: float | None,
    auto_recover: bool,
    hung_timeout_seconds: float,
    diagnosis_client: DiagnosisClient,
    diagnosis_backend: str | None,
    resume_after_recovery: bool,
    resume_argv: tuple[str, ...] | None,
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
    managed_session_id = persist_managed_events(parsed, workspace=workspace, store=store)
    store.add_process_observations(observations, session_id=managed_session_id)
    if signal is not None:
        store.add_signals((signal,), session_id=managed_session_id)

    if status == "running":
        status = _status(returncode, parsed.capabilities.has_completion_events)

    lingering = _find_lingering_command(parsed.normalized_events)
    resume_result = _maybe_resume_after_recovery(
        original_argv=argv,
        session_id=parsed.capabilities.persisted_session_id,
        diagnosis=diagnosis,
        verification=verification,
        enabled=resume_after_recovery,
        resume_argv=resume_argv,
        timeout_seconds=timeout_seconds,
    )
    if resume_result is None:
        resume_result = _maybe_resume_lingering_command(
            original_argv=argv,
            parsed=parsed,
            lingering=lingering,
            enabled=auto_recover,
            resume_argv=resume_argv,
            timeout_seconds=timeout_seconds,
        )
    if lingering is not None and resume_result is None and status.startswith("completed"):
        status = "awaiting_approval"
    if resume_result is not None:
        status = "recovered_and_resumed" if _resume_succeeded(resume_result) else "escalated"
        persist_managed_events(resume_result.parsed, workspace=workspace, store=store)

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
        resume_result=resume_result,
    )
    _persist_live_incident(
        store=store,
        session_id=managed_session_id,
        signal=signal,
        diagnosis=diagnosis,
        policy=policy,
        action_result=action_result,
        verification=verification,
        final_verification_resolved=_combined_verification_resolved(
            verification,
            lingering,
            resume_result,
        ),
        report=report,
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
        policy_allowed=policy.allowed
        if policy is not None
        else _lingering_policy_allowed(lingering, resume_result),
        verification_resolved=_combined_verification_resolved(
            verification,
            lingering,
            resume_result,
        ),
        diagnosis_backend=diagnosis_backend,
        resume_attempted=resume_result is not None,
        resume_returncode=resume_result.returncode if resume_result is not None else None,
        resume_status=_resume_status(resume_result)
        if resume_result is not None
        else None,
        resume_raw_event_count=_resume_raw_event_count(resume_result),
    )


def _status(returncode: int, has_completion_events: bool) -> str:
    if returncode == 0 and has_completion_events:
        return "completed"
    if returncode == 0:
        return "completed_without_adapter_completion"
    return "exited_nonzero"


def _report(
    captured: CapturedRun,
    status: str,
    *,
    resume_result: CapturedRun | None = None,
) -> str:
    lines = [
        f"Status: {status}",
        f"Return code: {captured.returncode}",
        f"Raw events: {len(captured.parsed.raw_events)}",
        f"Normalized events: {len(captured.parsed.normalized_events)}",
        f"Session ID: {captured.parsed.capabilities.persisted_session_id or 'unknown'}",
    ]
    if resume_result is not None:
        lines.append(f"Resume status: {_resume_status(resume_result)}")
        lines.append(f"Resume return code: {resume_result.returncode}")
        lines.append(f"Resume raw events: {len(resume_result.parsed.raw_events)}")
    return "\n".join(lines)


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
        is_descendant = parent_pid == root_pid or any(
            parent.pid == root_pid for parent in process.parents()
        )
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
    resume_result: CapturedRun | None,
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
    if resume_result is not None:
        lines.append(f"Resume status: {_resume_status(resume_result)}")
        lines.append(f"Resume return code: {resume_result.returncode}")
        lines.append(f"Resume raw events: {len(resume_result.parsed.raw_events)}")
    return "\n".join(lines)


def _incident_id(signal: Signal | None) -> str | None:
    if signal is None:
        return None
    suffix = signal.fingerprint.split(":", maxsplit=1)[-1]
    return f"live-{signal.kind.value.lower()}-{suffix}"


def _maybe_resume_after_recovery(
    *,
    original_argv: tuple[str, ...],
    session_id: str | None,
    diagnosis: Diagnosis | None,
    verification: VerificationResult | None,
    enabled: bool,
    resume_argv: tuple[str, ...] | None,
    timeout_seconds: float | None,
) -> CapturedRun | None:
    if not enabled or session_id is None or diagnosis is None:
        return None
    if verification is None or not verification.resolved:
        return None

    argv = resume_argv or _build_codex_resume_argv(original_argv, session_id, diagnosis.guidance)
    if argv is None:
        return None
    return run_and_capture_jsonl(argv, timeout_seconds=timeout_seconds)


def _maybe_resume_lingering_command(
    *,
    original_argv: tuple[str, ...],
    parsed: AdapterParseResult,
    lingering: tuple[str, str] | None,
    enabled: bool,
    resume_argv: tuple[str, ...] | None,
    timeout_seconds: float | None,
) -> CapturedRun | None:
    if lingering is None or not enabled:
        return None
    session_id = parsed.capabilities.persisted_session_id
    if session_id is None:
        return None

    evidence_id, command = lingering
    guidance = _lingering_command_guidance(evidence_id, command)
    argv = resume_argv or _build_codex_resume_argv(original_argv, session_id, guidance)
    if argv is None:
        return None
    return run_and_capture_jsonl(argv, timeout_seconds=timeout_seconds)


def _build_codex_resume_argv(
    original_argv: tuple[str, ...],
    session_id: str,
    guidance: str,
) -> tuple[str, ...] | None:
    if len(original_argv) < 2 or original_argv[0] != "codex" or original_argv[1] != "exec":
        return None

    sandbox = _codex_option_value(original_argv[2:], "--sandbox", "-s")
    if sandbox not in {"read-only", "workspace-write"}:
        return None
    if "--dangerously-bypass-approvals-and-sandbox" in original_argv:
        return None

    return (
        "codex",
        "exec",
        "--json",
        "--sandbox",
        sandbox,
        "resume",
        session_id,
        guidance,
    )


def _codex_option_value(
    argv: tuple[str, ...],
    long_name: str,
    short_name: str,
) -> str | None:
    for index, argument in enumerate(argv):
        if argument in {long_name, short_name}:
            if index + 1 < len(argv):
                return argv[index + 1]
            return None
        if argument.startswith(f"{long_name}="):
            return argument.split("=", maxsplit=1)[1]
    return None


def _find_lingering_command(events: tuple[NormalizedEvent, ...]) -> tuple[str, str] | None:
    open_commands: dict[str, tuple[str, str]] = {}
    for event in events:
        item = event.payload.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue

        item_id = str(item.get("id", event.evidence_id))
        command = str(item.get("command", "unknown command"))
        status = item.get("status")
        exit_code = item.get("exit_code")
        if status == "in_progress" or exit_code is None:
            open_commands[item_id] = (event.evidence_id, command)
        else:
            open_commands.pop(item_id, None)

    if not open_commands:
        return None
    return next(reversed(open_commands.values()))


def _lingering_command_guidance(evidence_id: str, command: str) -> str:
    return (
        "Deadman detected a command_execution event that remained in progress after the "
        f"turn completed. Evidence: {evidence_id}. Command: {command}. Stop the still-running "
        "background terminal or command from this Codex session. Do not start another long-running "
        "diagnostic. After stopping it, report that the lingering command was cleaned up."
    )


def _lingering_policy_allowed(
    lingering: tuple[str, str] | None,
    resume_result: CapturedRun | None,
) -> bool | None:
    if lingering is None:
        return None
    return resume_result is not None


def _lingering_verification_resolved(
    lingering: tuple[str, str] | None,
    resume_result: CapturedRun | None,
) -> bool | None:
    if lingering is None:
        return None
    return resume_result is not None and _resume_succeeded(resume_result)


def _combined_verification_resolved(
    verification: VerificationResult | None,
    lingering: tuple[str, str] | None,
    resume_result: CapturedRun | None,
) -> bool | None:
    if resume_result is not None:
        recovery_resolved = verification is None or verification.resolved
        return recovery_resolved and _resume_succeeded(resume_result)
    if verification is not None:
        return verification.resolved
    return _lingering_verification_resolved(lingering, resume_result)


def _resume_succeeded(resume_result: CapturedRun) -> bool:
    return (
        resume_result.returncode == 0
        and resume_result.parsed.capabilities.has_completion_events
    )


def _resume_status(resume_result: CapturedRun) -> str:
    return _status(
        resume_result.returncode,
        resume_result.parsed.capabilities.has_completion_events,
    )


def _resume_raw_event_count(resume_result: CapturedRun | None) -> int:
    if resume_result is None:
        return 0
    return len(resume_result.parsed.raw_events)


def _persist_live_incident(
    *,
    store: EvidenceStore,
    session_id: str,
    signal: Signal | None,
    diagnosis: Diagnosis | None,
    policy: PolicyDecision | None,
    action_result: ActionResult | None,
    verification: VerificationResult | None,
    final_verification_resolved: bool | None,
    report: str,
) -> None:
    if signal is None or diagnosis is None or policy is None:
        return

    incident = Incident(
        incident_id=_incident_id(signal) or f"live-{signal.fingerprint}",
        state=IncidentState.OPEN,
        signal=signal,
    )
    timestamp = time.time()
    incident = transition_incident(
        incident,
        to_state=IncidentState.DIAGNOSING,
        timestamp=timestamp,
        reason="deterministic signal opened incident",
        actor="deadman-supervisor",
        evidence_ids=signal.evidence_ids,
    )
    if not policy.allowed:
        incident = transition_incident(
            incident,
            to_state=IncidentState.AWAITING_APPROVAL,
            timestamp=timestamp,
            reason=policy.reason,
            actor="policy-engine",
            evidence_ids=signal.evidence_ids,
        )
    elif action_result is None:
        incident = transition_incident(
            incident,
            to_state=IncidentState.ESCALATED,
            timestamp=timestamp,
            reason="no supported live action was executed",
            actor="deadman-supervisor",
            evidence_ids=signal.evidence_ids,
        )
    else:
        incident = transition_incident(
            incident,
            to_state=IncidentState.RECOVERING,
            timestamp=timestamp,
            reason="policy authorized bounded action",
            actor="policy-engine",
            evidence_ids=action_result.evidence_ids,
            action_fingerprint=f"action:{signal.fingerprint}",
        )
        if verification is None:
            incident = transition_incident(
                incident,
                to_state=IncidentState.ESCALATED,
                timestamp=timestamp,
                reason="recovery produced no verification evidence",
                actor="deterministic-verifier",
                evidence_ids=action_result.evidence_ids,
            )
        else:
            incident = transition_incident(
                incident,
                to_state=IncidentState.VERIFYING,
                timestamp=timestamp,
                reason="bounded action completed",
                actor="deadman-supervisor",
                evidence_ids=action_result.evidence_ids,
            )
            incident = transition_incident(
                incident,
                to_state=(
                    IncidentState.RESOLVED
                    if final_verification_resolved
                    else IncidentState.ESCALATED
                ),
                timestamp=timestamp,
                reason=(
                    "measurable progress verified"
                    if final_verification_resolved
                    else "verification evidence was insufficient"
                ),
                actor="deterministic-verifier",
                evidence_ids=action_result.evidence_ids,
            )

    store.add_incident(incident, session_id=session_id)
    store.add_transitions(incident.incident_id, incident.transitions)
    store.add_canonical_transitions(
        incident,
        policy=policy,
        action_result=action_result,
    )
    store.add_diagnosis(incident.incident_id, diagnosis)
    store.add_policy_decision(incident.incident_id, policy)
    if action_result is not None:
        store.add_action_result(incident.incident_id, action_result)
    if verification is not None:
        store.add_verification_result(incident.incident_id, verification)
    store.add_report(incident.incident_id, report)
