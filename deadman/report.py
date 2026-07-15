"""Terminal report rendering."""

from __future__ import annotations

from deadman.domain import ReplayIncident


def render_incident_report(incident: ReplayIncident) -> str:
    """Render a compact self-contained incident report."""

    lines = [
        f"Incident: {incident.incident_id}",
        f"Signal: {incident.signal.kind.value}",
        f"Evidence: {', '.join(incident.signal.evidence_ids)}",
        f"Recommended action: {incident.diagnosis.recommended_action.value}",
        f"Policy: {'allowed' if incident.policy.allowed else 'blocked'} ({incident.policy.reason})",
        f"Verification: {'resolved' if incident.verification.resolved else 'escalated'}",
        f"Guidance: {incident.diagnosis.guidance}",
    ]
    return "\n".join(lines)
