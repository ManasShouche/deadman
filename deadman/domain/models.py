"""Small typed records shared by the D1 pipeline."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    """Incident severity used by detectors."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SignalKind(StrEnum):
    """Detector signal identifiers from the spec."""

    HUNG_PROCESS = "HUNG_PROCESS"
    REPEATED_FAILURE = "REPEATED_FAILURE"
    NO_PROGRESS = "NO_PROGRESS"
    SESSION_BUDGET_RISK = "SESSION_BUDGET_RISK"


class RecoveryAction(StrEnum):
    """Bounded recovery actions from the spec."""

    OBSERVE = "OBSERVE"
    TERMINATE_DESCENDANT_PROCESS = "TERMINATE_DESCENDANT_PROCESS"
    CANCEL_AND_RESUME = "CANCEL_AND_RESUME"
    CHECKPOINT_AND_RESPAWN = "CHECKPOINT_AND_RESPAWN"
    HALT_AND_ESCALATE = "HALT_AND_ESCALATE"


class RawAdapterEvent(BaseModel):
    """One raw JSONL line retained from the Codex adapter."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    line_number: int
    raw_line: str
    event_type: str
    parsed: dict[str, Any] | None = None
    parse_error: str | None = None


class NormalizedEvent(BaseModel):
    """Normalized event used by detectors without trusting Codex internals."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    raw_evidence_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CapabilityReport(BaseModel):
    """Capabilities observed in a concrete Codex JSONL trace."""

    model_config = ConfigDict(frozen=True)

    persisted_session_id: str | None = None
    has_completion_events: bool = False
    has_command_or_tool_completion_events: bool = False
    has_usage_fields: bool = False
    has_file_change_events: bool = False


class ProcessObservation(BaseModel):
    """Evidence about a supervised process at one point in time."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    root_pid: int
    pid: int
    parent_pid: int | None
    command_line: tuple[str, ...] = ()
    is_running: bool
    is_descendant: bool
    observed_at: float
    last_stdout_at: float | None = None
    last_stderr_at: float | None = None
    listening_ports: tuple[int, ...] = ()
    ready_pattern_matched: bool = False


class DetectorConfig(BaseModel):
    """Detector thresholds with conservative defaults."""

    model_config = ConfigDict(frozen=True)

    hung_timeout_seconds: float = 60.0
    repeated_failure_threshold: int = 3
    no_progress_attempt_threshold: int = 4
    session_budget_threshold: int = 1_000


class Signal(BaseModel):
    """Typed detector output. Signals never execute recovery directly."""

    model_config = ConfigDict(frozen=True)

    kind: SignalKind
    severity: Severity
    evidence_ids: tuple[str, ...]
    fingerprint: str
    details: dict[str, Any] = Field(default_factory=dict)


class AttemptObservation(BaseModel):
    """A completed attempt observed from replay or normalized adapter evidence."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    attempt_id: str
    completed_at: float
    workspace_fingerprint: str
    test_summary: str
    failure_signature: str | None = None
    assistant_hypothesis: str | None = None


class UsageObservation(BaseModel):
    """Usage telemetry observed for a Deadman session budget."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    observed_at: float
    used_units: int
    budget_units: int
    manual_checkpoint_requested: bool = False


class Diagnosis(BaseModel):
    """Validated model or fixture recommendation."""

    model_config = ConfigDict(frozen=True)

    classification: SignalKind
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: RecoveryAction
    rationale: str
    evidence_ids: tuple[str, ...]
    guidance: str
    requires_human_approval: bool


class PolicyDecision(BaseModel):
    """Deterministic authorization result for a diagnosis."""

    model_config = ConfigDict(frozen=True)

    allowed: bool
    action: RecoveryAction
    reason: str


class ActionResult(BaseModel):
    """Deterministic result from an attempted recovery action."""

    model_config = ConfigDict(frozen=True)

    action: RecoveryAction
    attempted: bool
    succeeded: bool
    evidence_ids: tuple[str, ...] = ()
    message: str
    artifact_path: str | None = None


class VerificationResult(BaseModel):
    """Deterministic post-action verification result."""

    model_config = ConfigDict(frozen=True)

    resolved: bool
    changed_progress_fingerprint: bool
    success_signal: str | None
    reason: str


class ReplayIncident(BaseModel):
    """Self-contained offline incident result."""

    model_config = ConfigDict(frozen=True)

    incident_id: str
    signal: Signal
    diagnosis: Diagnosis
    policy: PolicyDecision
    verification: VerificationResult
