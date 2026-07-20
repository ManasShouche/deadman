"""Rich terminal rendering for Deadman."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from deadman.adapter import SessionCandidate
from deadman.attach import LiveCodexProcess
from deadman.domain import ReplayIncident, RunSummary, WatchSnapshot
from deadman.recovery import RecoveryOutcome


def render_demo_dashboard(incidents: Iterable[ReplayIncident]) -> Panel:
    """Render the bundled demo as a compact terminal dashboard."""

    table = Table(expand=True)
    table.add_column("Scenario", style="cyan", no_wrap=True)
    table.add_column("Detect")
    table.add_column("Diagnose")
    table.add_column("Policy")
    table.add_column("Verify", justify="center")

    for incident in incidents:
        table.add_row(
            incident.incident_id,
            incident.signal.kind.value,
            incident.diagnosis.recommended_action.value,
            "allowed" if incident.policy.allowed else f"blocked: {incident.policy.reason}",
            "RESOLVED" if incident.verification.resolved else "ESCALATED",
        )

    return Panel(
        Group(_title(), table),
        title="Deadman demo",
        subtitle="Observe -> Detect -> Diagnose -> Recover -> Verify -> Report",
        border_style="green",
    )


def render_replay_result(incident: ReplayIncident) -> Panel:
    """Render one replay result."""

    table = Table.grid(padding=(0, 1))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("Incident", incident.incident_id)
    table.add_row("Signal", incident.signal.kind.value)
    table.add_row("Action", incident.diagnosis.recommended_action.value)
    table.add_row("Policy", "allowed" if incident.policy.allowed else incident.policy.reason)
    table.add_row("Verification", "RESOLVED" if incident.verification.resolved else "ESCALATED")
    table.add_row("Evidence", ", ".join(incident.signal.evidence_ids))
    return Panel(table, title="Deadman replay", border_style="green")


def render_report_panel(report: str) -> Panel:
    """Render a terminal report."""

    return Panel(report, title="Deadman incident report", border_style="cyan")


def render_run_summary(summary: RunSummary) -> Panel:
    """Render a supervised run summary."""

    table = Table.grid(padding=(0, 1))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("Status", summary.status)
    table.add_row("Return code", str(summary.returncode))
    table.add_row("Raw events", str(summary.raw_event_count))
    table.add_row("Normalized events", str(summary.normalized_event_count))
    table.add_row("Session ID", summary.session_id or "unknown")
    if summary.diagnosis_backend is not None:
        table.add_row("Diagnosis", summary.diagnosis_backend)
    if summary.signal_kind is not None:
        table.add_row("Signal", summary.signal_kind.value)
    if summary.recommended_action is not None:
        table.add_row("Action", summary.recommended_action.value)
    if summary.policy_allowed is not None:
        table.add_row("Policy", "allowed" if summary.policy_allowed else "blocked")
    if summary.verification_resolved is not None:
        table.add_row("Verification", "RESOLVED" if summary.verification_resolved else "ESCALATED")
    if summary.resume_attempted:
        table.add_row("Resume", summary.resume_status or "attempted")
        table.add_row("Resume code", str(summary.resume_returncode))
        table.add_row("Resume events", str(summary.resume_raw_event_count))
    table.add_row("SQLite", summary.database_path)
    return Panel(table, title="Deadman run", border_style="green")


def render_session_candidates(candidates: Iterable[SessionCandidate]) -> Panel:
    """Render attach candidates without implying that a process is owned or active."""

    table = Table(expand=True)
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Session")
    table.add_column("Source")
    table.add_column("Modified")
    for index, candidate in enumerate(candidates, start=1):
        table.add_row(
            str(index),
            candidate.session_id,
            candidate.source,
            datetime.fromtimestamp(candidate.modified_at)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S"),
        )
    return Panel(table, title="Codex session pairing", border_style="cyan")


def render_watch_snapshot(snapshot: WatchSnapshot) -> Panel:
    """Render one observe-only persisted-session status snapshot."""

    table = Table.grid(padding=(0, 1))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("Mode", "observe-only")
    table.add_row("Session", snapshot.session_id)
    table.add_row("Source", snapshot.source)
    table.add_row("Workspace", snapshot.cwd)
    table.add_row("Turn", snapshot.turn_state)
    table.add_row("Events", str(snapshot.event_count))
    table.add_row("New events", str(snapshot.new_event_count))
    table.add_row(
        "Last event",
        snapshot.last_event_kind.value if snapshot.last_event_kind is not None else "unknown",
    )
    table.add_row("Capabilities", ", ".join(snapshot.capabilities) or "none observed")
    table.add_row("Signals", ", ".join(snapshot.active_signals) or "none")
    table.add_row("Last progress", "not yet measured")
    table.add_row("Ownership", snapshot.ownership.value)
    return Panel(table, title="Deadman watch", border_style="yellow")


def render_live_codex_processes(processes: Iterable[LiveCodexProcess]) -> Panel:
    """Render discovered live Codex processes eligible for attach recovery."""

    table = Table(expand=True)
    table.add_column("#", justify="right", style="cyan")
    table.add_column("PID", justify="right")
    table.add_column("Session")
    table.add_column("Working directory")
    table.add_column("Started")
    for index, process in enumerate(processes, start=1):
        table.add_row(
            str(index),
            str(process.pid),
            process.session_id or "unlinked",
            str(process.cwd),
            datetime.fromtimestamp(process.create_time).astimezone().strftime("%H:%M:%S")
            if process.create_time
            else "unknown",
        )
    return Panel(table, title="Live Codex processes in this repo", border_style="cyan")


def render_recovery_outcome(outcome: RecoveryOutcome) -> Panel:
    """Render one attach/agent recovery incident result."""

    colors = {"recovered": "green", "awaiting_approval": "yellow", "escalated": "red"}
    border = colors.get(outcome.status, "yellow")
    table = Table.grid(padding=(0, 1))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("Status", outcome.status)
    table.add_row("Signal", outcome.signal.kind.value)
    table.add_row("Hung pid", str(outcome.signal.details.get("pid")))
    table.add_row("Recommended", outcome.diagnosis.recommended_action.value)
    table.add_row("Policy", "allowed" if outcome.policy.allowed else outcome.policy.reason)
    if outcome.action_result is not None:
        table.add_row("Action", outcome.action_result.message)
    if outcome.verification is not None:
        table.add_row(
            "Verification",
            "resolved" if outcome.verification.resolved else "escalated",
        )
        table.add_row("Reason", outcome.verification.reason)
    if outcome.incident is not None:
        table.add_row("Incident", outcome.incident.incident_id)
        table.add_row("Final state", outcome.incident.state.value)
    return Panel(table, title="Deadman recovery", border_style=border)


def _title() -> Text:
    text = Text()
    text.append("The session died. ", style="bold")
    text.append("The task didn't.", style="bold green")
    return text
