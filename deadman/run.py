"""Live completed-run supervision pipeline."""

from __future__ import annotations

from pathlib import Path

from deadman.adapter import CapturedRun, run_and_capture_jsonl
from deadman.domain import RunSummary
from deadman.store import EvidenceStore


def run_supervised_command(
    argv: tuple[str, ...],
    *,
    workspace: Path,
    database_path: Path | None = None,
    timeout_seconds: float | None = None,
) -> RunSummary:
    """Run a command, persist adapter evidence, and summarize deterministic status."""

    db_path = database_path or workspace / ".deadman" / "deadman.sqlite"
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
