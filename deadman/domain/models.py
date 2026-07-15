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


class Signal(BaseModel):
    """Typed detector output. Signals never execute recovery directly."""

    model_config = ConfigDict(frozen=True)

    kind: SignalKind
    severity: Severity
    evidence_ids: tuple[str, ...]
    fingerprint: str
    details: dict[str, Any] = Field(default_factory=dict)
