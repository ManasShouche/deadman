"""Rich terminal rendering for Deadman."""

from __future__ import annotations

from collections.abc import Iterable

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from deadman.domain import ReplayIncident, RunSummary


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
    if summary.signal_kind is not None:
        table.add_row("Signal", summary.signal_kind.value)
    if summary.recommended_action is not None:
        table.add_row("Action", summary.recommended_action.value)
    if summary.policy_allowed is not None:
        table.add_row("Policy", "allowed" if summary.policy_allowed else "blocked")
    if summary.verification_resolved is not None:
        table.add_row("Verification", "RESOLVED" if summary.verification_resolved else "ESCALATED")
    table.add_row("SQLite", summary.database_path)
    return Panel(table, title="Deadman run", border_style="green")


def _title() -> Text:
    text = Text()
    text.append("The session died. ", style="bold")
    text.append("The task didn't.", style="bold green")
    return text
